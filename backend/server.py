"""Wizard-Online WebSocket-Server (FastAPI + Socket.IO)."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
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

# Rate limiting: max events per sid per window. Excess events are silently dropped.
RATE_LIMIT_WINDOW = 1.0      # seconds
RATE_LIMIT_MAX = 5           # events allowed within the window
_rate_buckets: dict[str, deque] = defaultdict(lambda: deque(maxlen=RATE_LIMIT_MAX + 5))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("wizard")


def _rate_limited(sid: str) -> bool:
    """True if this sid has hit the per-second event quota."""
    now = time.monotonic()
    bucket = _rate_buckets[sid]
    while bucket and bucket[0] < now - RATE_LIMIT_WINDOW:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX:
        return True
    bucket.append(now)
    return False


def _log_event(event: str, sid: str, room: Optional["Room"] = None, extra: str = "") -> None:
    """Structured per-event log: room=X player=Y event=Z round=N phase=P [extra]."""
    if room:
        pid = room.sid_to_player.get(sid, "—")
        player = next((p for p in room.game.players if p.id == pid), None)
        pname = player.name if player else pid
        log.info(
            "room=%s player=%s event=%s round=%d phase=%s %s",
            room.id, pname, event,
            room.game.round_number, room.game.phase.value,
            extra,
        )
    else:
        log.info("room=— player=— event=%s sid=%s %s", event, sid, extra)


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
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


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
    try:
        state = room.game.public_state()
        state["room_id"] = room.id
        await sio.emit("game_state", state, room=room.id)
    except Exception as e:
        log.exception("broadcast public_state failed room=%s: %s", room.id, e)
        return
    for sid, player_id in list(room.sid_to_player.items()):
        try:
            hand = room.game.hand_for(player_id)
            blind_view = room.game.blind_view_for(player_id)
            legal_moves = room.game.legal_moves_for(player_id)
        except GameError:
            hand, blind_view, legal_moves = [], {}, []
        except Exception as e:
            log.warning("hand calc failed player=%s: %s", player_id, e)
            hand, blind_view, legal_moves = [], {}, []
        try:
            await sio.emit(
                "your_hand",
                {"hand": hand, "blind_view": blind_view, "legal_moves": legal_moves},
                to=sid,
            )
        except Exception as e:
            log.warning("your_hand emit failed sid=%s: %s", sid, e)


async def send_error(sid: str, msg: str) -> None:
    try:
        await sio.emit("error_message", {"message": msg}, to=sid)
    except Exception as e:
        log.warning("send_error failed sid=%s: %s", sid, e)


def safe_event(rate_limited: bool = True):
    """Decorator: wraps a Socket.IO handler so it can NEVER crash the server.
    - Catches every exception and logs it.
    - Optionally applies per-sid rate limiting (silent drop on excess).
    - Always returns None so socketio doesn't propagate.
    """
    def deco(fn):
        async def wrapper(sid: str, data=None):
            try:
                if rate_limited and _rate_limited(sid):
                    log.warning("rate-limited %s sid=%s", fn.__name__, sid)
                    return
                return await fn(sid, data)
            except GameError as ge:
                # Game rule violation — expected, send a friendly error to the client.
                log.warning("%s rejected sid=%s: %s", fn.__name__, sid, ge)
                try:
                    await send_error(sid, str(ge))
                except Exception:
                    pass
            except Exception as e:
                # Unexpected error — log full trace, do NOT crash, do NOT propagate.
                log.exception("%s CRASHED sid=%s: %s", fn.__name__, sid, e)
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco


@sio.event
async def connect(sid: str, environ: dict) -> None:
    try:
        log.info("[connect] sid=%s", sid)
    except Exception as e:
        log.warning("connect log failed: %s", e)


@sio.event
async def disconnect(sid: str) -> None:
    try:
        log.info("[disconnect] sid=%s", sid)
        # Clean rate-limit bucket
        _rate_buckets.pop(sid, None)
        room_id = sid_to_room.pop(sid, None)
        if not room_id:
            return
        room = rooms.get(room_id)
        if not room:
            return
        player_id = room.sid_to_player.pop(sid, None)

        if player_id:
            player = next((p for p in room.game.players if p.id == player_id), None)
            if player:
                player.is_online = False
            if room.game.phase is Phase.WAITING:
                asyncio.create_task(_grace_cleanup_lobby(room.id, player_id))

        try:
            await sio.leave_room(sid, room_id)
        except Exception:
            pass

        if room.sid_to_player or room.game.players:
            await broadcast_room(room)
    except Exception as e:
        log.exception("disconnect handler crashed sid=%s: %s", sid, e)


async def _grace_cleanup_lobby(room_id: str, player_id: str) -> None:
    """After the grace period, remove a still-offline lobby player. If the
    room is then empty, drop it. Wrapped in try/except so background-task
    crashes can't take the server down."""
    try:
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
            log.info("[grace-cleanup] removed offline lobby player=%s room=%s",
                     player_id, room_id)
        except GameError:
            pass
        if not room.sid_to_player and not room.game.players:
            rooms.pop(room_id, None)
            log.info("[grace-cleanup] removed empty room=%s", room_id)
        else:
            await broadcast_room(room)
    except Exception as e:
        log.exception("_grace_cleanup_lobby crashed room=%s player=%s: %s",
                      room_id, player_id, e)


@sio.event
@safe_event()
async def create_room(sid: str, data: dict) -> None:
    data = data or {}
    name = (data.get("name") or "").strip() or "Spieler"
    room_id = uuid.uuid4().hex[:6].upper()
    room = Room(id=room_id)
    rooms[room_id] = room
    _log_event("create_room", sid, room, f"name={name}")
    await _join(sid, room, name)
    await sio.emit("room_created", {"room_id": room_id}, to=sid)


@sio.event
@safe_event()
async def join_room(sid: str, data: dict) -> None:
    data = data or {}
    room_id = (data.get("room_id") or "").strip().upper()
    name = (data.get("name") or "").strip() or "Spieler"
    room = rooms.get(room_id)
    _log_event("join_room", sid, room, f"name={name} room_id={room_id}")
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
        await _do_rejoin(sid, room.id, existing.id, name)
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


async def _do_rejoin(sid: str, room_id: str, player_id: str, name: str) -> None:
    """Internal rejoin logic. Caller must already have validated/cleaned input.
    Looks up by player_id first, then name as fallback."""
    room = rooms.get(room_id)
    if not room:
        await sio.emit("rejoin_failed", {"reason": "no_room"}, to=sid)
        return

    player = None
    if player_id:
        player = next((p for p in room.game.players if p.id == player_id), None)
    if player is None and name:
        nlow = name.lower()
        player = next((p for p in room.game.players if p.name.lower() == nlow), None)

    if player is None:
        await sio.emit("rejoin_failed", {"reason": "no_player"}, to=sid)
        return

    cur = sid_to_room.get(sid)
    if cur and cur != room.id:
        await _leave_previous_room(sid)

    for old_sid, pid in list(room.sid_to_player.items()):
        if pid == player.id and old_sid != sid:
            room.sid_to_player.pop(old_sid, None)
            sid_to_room.pop(old_sid, None)

    player.is_online = True
    room.sid_to_player[sid] = player.id
    sid_to_room[sid] = room.id
    try:
        await sio.enter_room(sid, room.id)
    except Exception:
        pass
    await sio.emit(
        "joined",
        {"room_id": room.id, "player_id": player.id, "name": player.name},
        to=sid,
    )
    for msg in room.chat:
        try:
            await sio.emit("chat", msg, to=sid)
        except Exception:
            pass
    await broadcast_room(room)
    log.info("rejoin OK sid=%s -> player=%s (%s) in %s",
             sid, player.id, player.name, room.id)


@sio.event
@safe_event(rate_limited=False)  # rejoin needs to bypass rate limit (auto-fired on reconnect)
async def rejoin(sid: str, data: dict) -> None:
    """Reconnect handler: client provides {room_id, player_id?, name?}.
    Lookup priority: player_id first, then name as fallback."""
    data = data or {}
    room_id = (data.get("room_id") or "").strip().upper()
    player_id = (data.get("player_id") or "").strip()
    name = (data.get("name") or "").strip()
    log.info("[rejoin] sid=%s room=%s player_id=%s name=%s",
             sid, room_id, player_id or "—", name or "—")
    await _do_rejoin(sid, room_id, player_id, name)


@sio.event
@safe_event()
async def list_rooms(sid: str, data: dict = None) -> None:
    """Return a snapshot of all currently active rooms."""
    out = []
    for r in rooms.values():
        try:
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
        except Exception as e:
            log.warning("list_rooms entry skipped (room=%s): %s", getattr(r, "id", "?"), e)
    out.sort(key=lambda x: (not x["joinable"], x["room_id"]))
    await sio.emit("rooms_list", {"rooms": out}, to=sid)


@sio.event
@safe_event()
async def start_game(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        return
    _log_event("start_game", sid, room)
    room.game.start_game()  # GameError caught by safe_event
    log_room(room, "after start_game")
    await broadcast_room(room)


@sio.event
@safe_event()
async def place_bid(sid: str, data: dict) -> None:
    data = data or {}
    room = _room_of(sid)
    if not room:
        return  # silently ignore — client probably stale, rejoin will fix
    player_id = room.sid_to_player.get(sid)
    if not player_id:
        return  # silently ignore — sid not bound to a player
    try:
        bid = int(data.get("bid"))
    except (TypeError, ValueError):
        return  # silent ignore — malformed payload
    _log_event("place_bid", sid, room, f"bid={bid}")
    room.game.place_bid(player_id, bid)  # GameError caught by safe_event
    await broadcast_room(room)


@sio.event
@safe_event()
async def play_card(sid: str, data: dict) -> None:
    data = data or {}
    room = _room_of(sid)
    if not room:
        return
    player_id = room.sid_to_player.get(sid)
    if not player_id:
        return
    card_data = data.get("card") or {}
    _log_event("play_card", sid, room, f"card={card_data}")
    if card_data.get("hidden"):
        room.game.play_blind(player_id)
    else:
        card = card_from_dict(card_data)
        room.game.play_card(player_id, card)
    await broadcast_room(room)


@sio.event
@safe_event()
async def next_round(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        return
    _log_event("next_round", sid, room)
    room.game.start_next_round()  # GameError caught by safe_event (silently next time)
    await broadcast_room(room)


@sio.event
@safe_event()
async def leave_room(sid: str, data: dict = None) -> None:
    """Explicit leave: client tells the server they're done with this room."""
    room = _room_of(sid)
    if not room:
        try:
            await sio.emit("left_room", {}, to=sid)
        except Exception:
            pass
        return
    player_id = room.sid_to_player.pop(sid, None)
    sid_to_room.pop(sid, None)
    _log_event("leave_room", sid, room, f"player_id={player_id}")
    if player_id:
        if room.game.phase is Phase.WAITING:
            try:
                room.game.remove_player(player_id)
            except GameError:
                pass
        else:
            p = next((p for p in room.game.players if p.id == player_id), None)
            if p:
                p.is_online = False
    try:
        await sio.leave_room(sid, room.id)
    except Exception:
        pass
    try:
        await sio.emit("left_room", {}, to=sid)
    except Exception:
        pass
    if not room.sid_to_player and not room.game.players:
        rooms.pop(room.id, None)
        log.info("room=%s removed (empty after leave)", room.id)
    else:
        await broadcast_room(room)


@sio.event
@safe_event()
async def chat_message(sid: str, data: dict) -> None:
    data = data or {}
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
