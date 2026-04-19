"""Wizard-Online WebSocket-Server (FastAPI + Socket.IO)."""
from __future__ import annotations

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
    return {"status": "ok", "rooms": len(rooms)}


fastapi_app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


async def broadcast_room(room: Room) -> None:
    state = room.game.public_state()
    state["room_id"] = room.id
    await sio.emit("game_state", state, room=room.id)
    for sid, player_id in room.sid_to_player.items():
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
    print(f"[connect] {sid}")


@sio.event
async def disconnect(sid: str) -> None:
    print(f"[disconnect] {sid}")
    room_id = sid_to_room.pop(sid, None)
    if not room_id:
        return
    room = rooms.get(room_id)
    if not room:
        return
    player_id = room.sid_to_player.pop(sid, None)
    if player_id and room.game.phase is Phase.WAITING:
        try:
            room.game.remove_player(player_id)
        except GameError:
            pass
    await sio.leave_room(sid, room_id)
    if not room.sid_to_player:
        rooms.pop(room_id, None)
    else:
        await broadcast_room(room)


@sio.event
async def create_room(sid: str, data: dict) -> None:
    name = (data.get("name") or "").strip() or "Spieler"
    room_id = uuid.uuid4().hex[:6].upper()
    room = Room(id=room_id)
    rooms[room_id] = room
    await _join(sid, room, name)
    await sio.emit("room_created", {"room_id": room_id}, to=sid)


@sio.event
async def join_room(sid: str, data: dict) -> None:
    room_id = (data.get("room_id") or "").strip().upper()
    name = (data.get("name") or "").strip() or "Spieler"
    room = rooms.get(room_id)
    if not room:
        await send_error(sid, "Raum nicht gefunden.")
        return
    await _join(sid, room, name)


async def _join(sid: str, room: Room, name: str) -> None:
    player_id = uuid.uuid4().hex[:8]
    try:
        room.game.add_player(player_id, name)
    except GameError as e:
        await send_error(sid, str(e))
        return
    room.sid_to_player[sid] = player_id
    sid_to_room[sid] = room.id
    await sio.enter_room(sid, room.id)
    await sio.emit("joined", {"room_id": room.id, "player_id": player_id, "name": name}, to=sid)
    for msg in room.chat:
        await sio.emit("chat", msg, to=sid)
    await broadcast_room(room)


@sio.event
async def start_game(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        return
    try:
        room.game.start_game()
    except GameError as e:
        await send_error(sid, str(e))
        return
    await broadcast_room(room)


@sio.event
async def place_bid(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        return
    player_id = room.sid_to_player.get(sid)
    try:
        bid = int(data.get("bid"))
    except (TypeError, ValueError):
        await send_error(sid, "Ungültiger Tipp.")
        return
    try:
        room.game.place_bid(player_id, bid)
    except GameError as e:
        await send_error(sid, str(e))
        return
    await broadcast_room(room)


@sio.event
async def play_card(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        return
    player_id = room.sid_to_player.get(sid)
    card_data = data.get("card")
    try:
        if card_data and card_data.get("hidden"):
            room.game.play_blind(player_id)
        else:
            card = card_from_dict(card_data or {})
            room.game.play_card(player_id, card)
    except GameError as e:
        await send_error(sid, str(e))
        return
    except Exception:
        await send_error(sid, "Ungültige Karte.")
        return
    await broadcast_room(room)


@sio.event
async def next_round(sid: str, data: dict) -> None:
    room = _room_of(sid)
    if not room:
        return
    try:
        room.game.start_next_round()
    except GameError as e:
        await send_error(sid, str(e))
        return
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
