"""Wizard-Online WebSocket-Server (FastAPI + Socket.IO)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import socketio
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.cards import card_from_dict
from backend.game import WizardGame, GameError, Phase

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Grace period before a disconnected lobby player is removed (seconds).
LOBBY_GRACE_SECONDS = 45

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("wizard")


@dataclass
class Room:
    id: str
    game: WizardGame = field(default_factory=WizardGame)
    sid_to_player: dict[str, str] = field(default_factory=dict)
    chat: list[dict] = field(default_factory=list)


rooms: dict[str, Room] = {}
sid_to_room: dict[str, str] = {}


sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
fastapi_app = FastAPI()


@fastapi_app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@fastapi_app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "rooms": len(rooms),
        "active_sids": len(sid_to_room),
    }


fastapi_app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def log_room(room: Room, where: str) -> None:
    g = room.game
    hands = ", ".join(f"{p.name}={len(p.hand)}" for p in g.players)
    log.info(
        "[%s] room=%s phase=%s round=%d/%d trick=%d current=%s hands=[%s]",
        where,
        room.id,
        g.phase.value,
        g.round_number,
        g.total_rounds(),
        g.tricks_played_this_round,
        (g.current_player().name if g.current_player() else "—"),
        hands,
    )


async def broadcast_room(room: Room) -> None:
    state = room.game.public_state()
    state["room_id"] = room.id
    await sio.emit("game_state", state, room=room.id)
    for sid, player_id in list(room.sid_to_player.items()):
        try:
            hand = room.game.hand_for(player_id)
            blind_view = room.game.blind_view_for(player_id)
            legal_moves = room.game.legal_moves_for(player_id)
        except GameError:
            hand, blind_view, legal_moves = [], {}, []
        await sio.emit(
            "your_hand",
            {"hand": hand, "blind_view": blind_view, "legal_moves": legal_moves},
            to=sid,
        )


async def send_error(sid: str, msg: str) -> None:
    await sio.emit("error_message", {"message": msg}, to=sid)


@sio.event
async def connect(sid: str, environ: dict) -> None:
    log.info("[connect] sid=%s", sid)


@sio.event
async def disconnect(sid: str) -> None:
    log.info("[disconnect] sid=%s", sid)
    room_id = sid_to_room.pop(sid, None)
    if not room_id:
        return
    room = rooms.get(room_id)
    if not room:
        return
    player_id = room.sid_to_player.pop(sid, None)

    # Mark the player as offline (informational for other clients).
    # Don't remove yet — we wait LOBBY_GRACE_SECONDS for a reconnect.
    if player_id:
        player = next((p for p in room.game.players if p.id == player_id), None)
        if player:
            player.is_online = False
        # Schedule a delayed cleanup task only for lobby-phase players.
        # During an active game we KEEP offline players forever; the game can
        # pause on their turn and they can reconnect by name later.
        if room.game.phase is Phase.WAITING:
            asyncio.create_task(_grace_cleanup_lobby(room.id, player_id))

    try:
        await sio.leave_room(sid, room_id)
    except Exception:
        pass

    if room.sid_to_player or room.game.players:
        await broadcast_room(room)


async def _grace_cleanup_lobby(room_id: str, player_id: str) -> None:
    """After the grace period, remove a still-offline lobby player. If the
    room is then empty, drop it."""
    await asyncio.sleep(LOBBY_GRACE_SECONDS)
    room = rooms.get(room_id)
    if not room:
        return
    player = next((p for p in room.game.players if p.id == player_id), None)
    if not player or player.is_online:
        return
    if room.game.phase is not Phase.WAITING:
        return
    try:
        room.game.remove_player(player_id)
        log.info("[grace-cleanup] removed offline lobby player=%s room=%s", player_id, room_id)
    except GameError:
        pass
    if not room.sid_to_player and not room.game.players:
        rooms.pop(room_id, None)
        log.info("[grace-cleanup] removed empty room=%s", room_id)
    else:
        await broadcast_room(room)


@sio.event
async def create_room(sid: str, data: dict) -> None:
    name = (data.get("name") or "").strip() or "Spieler"
    room_id = uuid.uuid4().hex[:6].upper()
    room = Room(id=room_id)
    rooms[room_id] = room
    log.info("[create_room] sid=%s name=%s -> room=%s", sid, name, room_id)
    await _join(sid, room, name)
    await sio.emit("room_created", {"room_id": room_id}, to=sid)


@sio.event
async def join_room(sid: str, data: dict) -> None:
    room_id = (data.get("room_id") or "").strip().upper()
    name = (data.get("name") or "").strip() or "Spieler"
    log.info("[join_room] sid=%s name=%s room=%s", sid, name, room_id)
    room = rooms.get(room_id)
    if not room:
        await send_error(sid, "Raum nicht gefunden.")
        await sio.emit("rejoin_failed", {"reason": "no_room"}, to=sid)
        return

    # If a player with the same name already exists in this room AND is offline,
    # treat this as a reconnect (don't create a duplicate seat).
    nlow = name.lower()
    existing = next(
        (p for p in room.game.players if p.name.lower() == nlow and not p.is_online),
        None,
    )
    if existing:
        await rejoin(sid, {"room_id": room.id, "player_id": existing.id, "name": name})
        return

    await _join(sid, room, name)


async def _leave_previous_room(sid: str) -> None:
    prev_id = sid_to_room.pop(sid, None)
    if not prev_id:
        return
    prev_room = rooms.get(prev_id)
    if not prev_room:
        return
    prev_player_id = prev_room.sid_to_player.pop(sid, None)
    if prev_player_id:
        p = next((pl for pl in prev_room.game.players if pl.id == prev_player_id), None)
        if p:
            p.is_online = False
        if prev_room.game.phase is Phase.WAITING:
            asyncio.create_task(_grace_cleanup_lobby(prev_id, prev_player_id))
    try:
        await sio.leave_room(sid, prev_id)
    except Exception:
        pass
    if prev_room.sid_to_player or prev_room.game.players:
        await broadcast_room(prev_room)


async def _join(sid: str, room: Room, name: str) -> None:
    await _leave_previous_room(sid)
    player_id = uuid.uuid4().hex[:8]
    try:
        room.game.add_player(player_id, name)
    except GameError as e:
        await send_error(sid, str(e))
        return
    room.sid_to_player[sid] = player_id
    sid_to_room[sid] = room.id
    await sio.enter_room(sid, room.id)
    await sio.emit(
        "joined",
        {"room_id": room.id, "player_id": player_id, "name": name},
        to=sid,
    )
    for msg in room.chat:
        await sio.emit("chat", msg, to=sid)
    await broadcast_room(room)


@sio.event
async def rejoin(sid: str, data: dict) -> None:
    """Reconnect handler: client provides existing {room_id, player_id?, name?}
    and gets its sid re-mapped to the existing player.

    Lookup priority:
      1. player_id (most precise, survives name collisions)
      2. name match (works after a hard reload when only name was kept)

    No new player is created here — for that, use create_room/join_room.
    """
    room_id = (data.get("room_id") or "").strip().upper()
    player_id = (data.get("player_id") or "").strip()
    name = (data.get("name") or "").strip()
    log.info("[rejoin] sid=%s room=%s player_id=%s name=%s",
             sid, room_id, player_id or "—", name or "—")

    room = rooms.get(room_id)
    if not room:
        await sio.emit("rejoin_failed", {"reason": "no_room"}, to=sid)
        return

    player = None
    if player_id:
        player = next((p for p in room.game.players if p.id == player_id), None)
    if player is None and name:
        # Name fallback (case-insensitive, trimmed)
        nlow = name.lower()
        player = next((p for p in room.game.players if p.name.lower() == nlow), None)

    if player is None:
        await sio.emit("rejoin_failed", {"reason": "no_player"}, to=sid)
        return

    # If this sid is currently mapped to a different room, leave it.
    cur = sid_to_room.get(sid)
    if cur and cur != room.id:
        await _leave_previous_room(sid)

    # Drop any stale sid mappings still pointing to this player
    for old_sid, pid in list(room.sid_to_player.items()):
        if pid == player.id and old_sid != sid:
            room.sid_to_player.pop(old_sid, None)
            sid_to_room.pop(old_sid, None)

    player.is_online = True
    room.sid_to_player[sid] = player.id
    sid_to_room[sid] = room.id
    await sio.enter_room(sid, room.id)
    await sio.emit(
        "joined",
        {"room_id": room.id, "player_id": player.id, "name": player.name},
        to=sid,
    )
    for msg in room.chat:
        await sio.emit("chat", msg, to=sid)
    await broadcast_room(room)
    log.info("[rejoin OK] sid=%s -> player=%s (%s) in %s",
             sid, player.id, player.name, room.id)


@sio.event
async def list_rooms(sid: str, data: dict = None) -> None:
    """Return a snapshot of all currently active rooms."""
    out = []
    for r in rooms.values():
        ph = r.game.phase
        out.append({
            "room_id": r.id,
            "players": len(r.game.players),
            "max_players": r.game.MAX_PLAYERS,
            "min_players": r.game.MIN_PLAYERS,
            "status": "lobby" if ph is Phase.WAITING else "ingame",
            "joinable": ph is Phase.WAITING and len(r.game.players) < r.game.MAX_PLAYERS,
            "player_names": [p.name for p in r.game.players],
        })
    out.sort(key=lambda x: (not x["joinable"], x["room_id"]))
    await sio.emit("rooms_list", {"rooms": out}, to=sid)


@sio.event
async def start_game(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        return
    log.info("[start_game] sid=%s room=%s", sid, room.id)
    try:
        room.game.start_game()
    except GameError as e:
        await send_error(sid, str(e))
        return
    log_room(room, "after start_game")
    await broadcast_room(room)


@sio.event
async def place_bid(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        await send_error(sid, "Verbindung verloren — bitte neu laden.")
        return
    player_id = room.sid_to_player.get(sid)
    if not player_id:
        await send_error(sid, "Du bist nicht im Spiel registriert.")
        return
    try:
        bid = int(data.get("bid"))
    except (TypeError, ValueError):
        await send_error(sid, "Ungültiger Tipp.")
        return
    log.info("[place_bid] sid=%s room=%s player=%s bid=%d", sid, room.id, player_id, bid)
    try:
        room.game.place_bid(player_id, bid)
    except GameError as e:
        log.warning("[place_bid REJECTED] %s", e)
        await send_error(sid, str(e))
        return
    log_room(room, "after place_bid")
    await broadcast_room(room)


@sio.event
async def play_card(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        await send_error(sid, "Verbindung verloren — bitte neu laden.")
        return
    player_id = room.sid_to_player.get(sid)
    if not player_id:
        await send_error(sid, "Du bist nicht im Spiel registriert.")
        return
    card_data = data.get("card")
    log.info(
        "[play_card] sid=%s room=%s player=%s card=%s",
        sid, room.id, player_id, card_data,
    )
    try:
        if card_data and card_data.get("hidden"):
            room.game.play_blind(player_id)
        else:
            card = card_from_dict(card_data or {})
            room.game.play_card(player_id, card)
    except GameError as e:
        log.warning("[play_card REJECTED] %s", e)
        await send_error(sid, str(e))
        return
    except Exception as e:
        log.exception("[play_card FAILED] %s", e)
        await send_error(sid, "Ungültige Karte.")
        return
    log_room(room, "after play_card")
    await broadcast_room(room)


@sio.event
async def next_round(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        return
    log.info("[next_round] sid=%s room=%s", sid, room.id)
    try:
        room.game.start_next_round()
    except GameError as e:
        log.warning("[next_round REJECTED] %s", e)
        await send_error(sid, str(e))
        return
    log_room(room, "after next_round")
    await broadcast_room(room)


@sio.event
async def chat_message(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        return
    player_id = room.sid_to_player.get(sid)
    player = next((p for p in room.game.players if p.id == player_id), None)
    text = (data.get("text") or "").strip()
    if not text or not player:
        return
    msg = {"from": player.name, "text": text[:500]}
    room.chat.append(msg)
    room.chat = room.chat[-100:]
    await sio.emit("chat", msg, room=room.id)


def _room_of(sid: str) -> Optional[Room]:
    room_id = sid_to_room.get(sid)
    if not room_id:
        return None
    return rooms.get(room_id)


app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.server:app", host="0.0.0.0", port=port, reload=True)
