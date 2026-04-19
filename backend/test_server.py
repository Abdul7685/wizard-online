"""End-to-End-Test: drei simulierte Spieler spielen eine Runde über Socket.IO."""
from __future__ import annotations

import asyncio
import sys

import socketio

SERVER_URL = "http://localhost:8000"


class Bot:
    def __init__(self, name: str) -> None:
        self.name = name
        self.sio = socketio.AsyncClient()
        self.room_id: str | None = None
        self.player_id: str | None = None
        self.hand: list[dict] = []
        self.game_state: dict | None = None
        self._register_handlers()
        self.errors: list[str] = []

    def _register_handlers(self) -> None:
        @self.sio.on("joined")
        async def _joined(data):
            self.room_id = data["room_id"]
            self.player_id = data["player_id"]
            print(f"[{self.name}] beigetreten. Raum={self.room_id} Spieler-ID={self.player_id}")

        @self.sio.on("room_created")
        async def _created(data):
            print(f"[{self.name}] Raum erstellt: {data['room_id']}")

        @self.sio.on("game_state")
        async def _state(data):
            self.game_state = data

        @self.sio.on("your_hand")
        async def _hand(data):
            self.hand = data["hand"]

        @self.sio.on("error_message")
        async def _err(data):
            self.errors.append(data["message"])
            print(f"[{self.name}] FEHLER: {data['message']}")

        @self.sio.on("chat")
        async def _chat(data):
            print(f"[chat] {data['from']}: {data['text']}")

    async def connect(self) -> None:
        await self.sio.connect(SERVER_URL)

    async def disconnect(self) -> None:
        await self.sio.disconnect()


async def wait_for(condition_fn, timeout: float = 3.0, interval: float = 0.05) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        if condition_fn():
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return False


async def main() -> int:
    alice = Bot("Alice")
    bob = Bot("Bob")
    carol = Bot("Carol")

    await asyncio.gather(alice.connect(), bob.connect(), carol.connect())

    await alice.sio.emit("create_room", {"name": "Alice"})
    if not await wait_for(lambda: alice.room_id is not None):
        print("FAIL: Raum wurde nicht erstellt.")
        return 1

    room_id = alice.room_id
    await bob.sio.emit("join_room", {"name": "Bob", "room_id": room_id})
    await carol.sio.emit("join_room", {"name": "Carol", "room_id": room_id})

    if not await wait_for(lambda: bob.room_id is not None and carol.room_id is not None):
        print("FAIL: Bob/Carol nicht beigetreten.")
        return 1

    print(f"Alle 3 Spieler im Raum {room_id}")

    await alice.sio.emit("start_game", {})
    if not await wait_for(lambda: alice.game_state and alice.game_state["phase"] == "bidding"):
        print("FAIL: Spiel nicht gestartet.")
        return 1

    bots_by_id = {b.player_id: b for b in (alice, bob, carol)}

    def bot_by_current() -> Bot:
        pid = alice.game_state["current_player"]
        return bots_by_id[pid]

    async def refresh_until(pred, label: str) -> bool:
        ok = await wait_for(lambda: alice.game_state and pred(alice.game_state))
        if not ok:
            print(f"FAIL: Warte-Bedingung '{label}' nicht erreicht. State={alice.game_state}")
        return ok

    for _ in range(3):
        current = bot_by_current()
        # Tipp-Zwang respektieren: verbotene Zahl ausweichen
        forbidden = alice.game_state.get("forbidden_bid")
        bid = 0 if forbidden != 0 else 1
        await current.sio.emit("place_bid", {"bid": bid})
        await asyncio.sleep(0.1)

    if not await refresh_until(lambda s: s["phase"] == "playing", "playing"):
        return 1

    print(f"Alle Tipps abgegeben. Trumpf={alice.game_state['trump_suit']}")

    # Runde 1 ist blind -> jeder spielt die einzige Karte
    for _ in range(3):
        current = bot_by_current()
        print(f"[{current.name}] spielt blind")
        await current.sio.emit("play_card", {"card": {"hidden": True}})
        await asyncio.sleep(0.2)

    if not await refresh_until(
        lambda s: s["phase"] in ("round_done", "game_over"),
        "round_done",
    ):
        return 1

    print("\nRunde fertig!")
    for p in alice.game_state["players"]:
        print(f"  {p['name']}: Tipp={p['bid']} Stiche={p['tricks']} Punkte={p['score']}")

    await alice.sio.emit("chat_message", {"text": "gg wp!"})
    await asyncio.sleep(0.3)

    await asyncio.gather(alice.disconnect(), bob.disconnect(), carol.disconnect())

    any_errors = alice.errors + bob.errors + carol.errors
    if any_errors:
        print(f"\nFEHLER aufgetreten: {any_errors}")
        return 1

    print("\nOK - Alles lief durch!")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
