"""Wizard-Spielzustand nach Hausregeln.

Hausregeln:
- Kein Kartengeber; Startspieler rotiert im Uhrzeigersinn.
- Trumpfkarte wird aufgedeckt: Farbkarte -> Trumpf, Wizard/Narr -> kein Trumpf.
- Letzte Runde: kein Trumpf.
- Letzter Tipp-Abgeber darf nicht so tippen, dass Summe = Rundennummer.
- Runde 1: Spieler sieht seine eigene Karte NICHT, aber die der anderen.
- Wizard/Narr dürfen nur gespielt werden, wenn keine Bedienfarbe vorhanden.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from backend.cards import(
    Card,
    CardType,
    Suit,
    card_to_dict,
    is_legal_play,
    lead_suit_from_plays,
    legal_cards_in_hand,
    score_round,
    shuffled_deck,
    trick_winner,
)


class Phase(str, Enum):
    WAITING = "waiting"
    BIDDING = "bidding"
    PLAYING = "playing"
    ROUND_DONE = "round_done"
    GAME_OVER = "game_over"


@dataclass
class Player:
    id: str
    name: str
    hand: list[Card] = field(default_factory=list)
    bid: Optional[int] = None
    tricks_this_round: int = 0
    total_score: int = 0
    scores_per_round: list[int] = field(default_factory=list)


@dataclass
class TrickPlay:
    player_id: str
    card: Card


class GameError(Exception):
    pass


class WizardGame:
    MIN_PLAYERS = 3
    MAX_PLAYERS = 6

    def __init__(self, seed: Optional[int] = None) -> None:
        self.players: list[Player] = []
        self.phase: Phase = Phase.WAITING
        self.round_number: int = 0
        self.start_player_index: int = 0
        self.current_player_index: int = 0
        self.trump_suit: Optional[Suit] = None
        self.trump_card: Optional[Card] = None
        self.current_trick: list[TrickPlay] = []
        self.tricks_played_this_round: int = 0
        self.last_trick_winner_id: Optional[str] = None
        self.last_completed_trick: Optional[dict] = None
        self._rng = random.Random(seed)

    # ---- Lobby ----

    def add_player(self, player_id: str, name: str) -> Player:
        if self.phase is not Phase.WAITING:
            raise GameError("Spiel läuft bereits.")
        if len(self.players) >= self.MAX_PLAYERS:
            raise GameError("Spiel ist voll.")
        if any(p.id == player_id for p in self.players):
            raise GameError("Spieler ist bereits im Spiel.")
        player = Player(id=player_id, name=name)
        self.players.append(player)
        return player

    def remove_player(self, player_id: str) -> None:
        if self.phase is not Phase.WAITING:
            raise GameError("Kann Spieler nicht entfernen, Spiel läuft.")
        self.players = [p for p in self.players if p.id != player_id]

    def total_rounds(self) -> int:
        if not self.players:
            return 0
        return 60 // len(self.players)

    # ---- Rundenfluss ----

    def start_game(self) -> None:
        if self.phase is not Phase.WAITING:
            raise GameError("Spiel hat bereits begonnen.")
        if len(self.players) < self.MIN_PLAYERS:
            raise GameError(f"Mindestens {self.MIN_PLAYERS} Spieler nötig.")
        self.round_number = 0
        self.start_player_index = self._rng.randrange(len(self.players))
        self._start_next_round()

    def _start_next_round(self) -> None:
        self.round_number += 1
        if self.round_number > self.total_rounds():
            self.phase = Phase.GAME_OVER
            return

        for player in self.players:
            player.hand = []
            player.bid = None
            player.tricks_this_round = 0

        deck = shuffled_deck(self._rng)
        cards_per_player = self.round_number
        n = len(self.players)
        for _ in range(cards_per_player):
            for i in range(n):
                idx = (self.start_player_index + i) % n
                self.players[idx].hand.append(deck.pop())

        self.trump_card = None
        self.trump_suit = None
        self.current_trick = []
        self.tricks_played_this_round = 0
        self.last_trick_winner_id = None

        is_last_round = self.round_number == self.total_rounds()
        if not is_last_round and deck:
            self.trump_card = deck.pop()
            if self.trump_card.type is CardType.NUMBER:
                self.trump_suit = self.trump_card.suit

        self.phase = Phase.BIDDING
        self.current_player_index = self.start_player_index

    def place_bid(self, player_id: str, bid: int) -> None:
        if self.phase is not Phase.BIDDING:
            raise GameError("Keine Tipp-Phase gerade.")
        if self.players[self.current_player_index].id != player_id:
            raise GameError("Du bist nicht dran.")
        if bid < 0 or bid > self.round_number:
            raise GameError(f"Tipp muss zwischen 0 und {self.round_number} sein.")

        remaining_after = sum(1 for p in self.players if p.bid is None) - 1
        if remaining_after == 0:
            current_sum = sum((p.bid or 0) for p in self.players if p.bid is not None)
            if current_sum + bid == self.round_number:
                raise GameError(
                    f"Tipp-Zwang: Die Summe darf nicht {self.round_number} ergeben. "
                    f"Wähle einen anderen Tipp."
                )

        self._player_by_id(player_id).bid = bid

        if all(p.bid is not None for p in self.players):
            self.phase = Phase.PLAYING
            self.current_player_index = self.start_player_index
        else:
            self.current_player_index = (self.current_player_index + 1) % len(self.players)

    def forbidden_last_bid(self) -> Optional[int]:
        """Für den aktuellen letzten Tipp-Abgeber: die verbotene Zahl (sonst None)."""
        if self.phase is not Phase.BIDDING:
            return None
        remaining_after = sum(1 for p in self.players if p.bid is None) - 1
        if remaining_after != 0:
            return None
        current_sum = sum((p.bid or 0) for p in self.players if p.bid is not None)
        forbidden = self.round_number - current_sum
        if 0 <= forbidden <= self.round_number:
            return forbidden
        return None

    def play_card(self, player_id: str, card: Card) -> None:
        if self.phase is not Phase.PLAYING:
            raise GameError("Keine Spiel-Phase gerade.")
        if self.players[self.current_player_index].id != player_id:
            raise GameError("Du bist nicht dran.")

        player = self._player_by_id(player_id)
        lead_suit = lead_suit_from_plays([p.card for p in self.current_trick])
        if not is_legal_play(card, player.hand, lead_suit):
            raise GameError("Ungültiger Zug: du musst die Bedienfarbe spielen.")

        if not self.current_trick:
            self.last_completed_trick = None

        player.hand.remove(card)
        self.current_trick.append(TrickPlay(player_id=player_id, card=card))

        if len(self.current_trick) == len(self.players):
            self._resolve_trick()
        else:
            self.current_player_index = (self.current_player_index + 1) % len(self.players)

    def play_blind(self, player_id: str) -> None:
        """Runde 1: Spieler sieht seine Karte nicht — spielt sie blind."""
        if self.round_number != 1:
            raise GameError("Blind-Spiel nur in Runde 1.")
        if self.phase is not Phase.PLAYING:
            raise GameError("Keine Spiel-Phase gerade.")
        if self.players[self.current_player_index].id != player_id:
            raise GameError("Du bist nicht dran.")
        player = self._player_by_id(player_id)
        if not player.hand:
            raise GameError("Keine Karte zum Spielen.")
        self.play_card(player_id, player.hand[0])

    def _resolve_trick(self) -> None:
        plays = [tp.card for tp in self.current_trick]
        winner_idx_in_trick = trick_winner(plays, self.trump_suit)
        winner_id = self.current_trick[winner_idx_in_trick].player_id
        winner = self._player_by_id(winner_id)
        winner.tricks_this_round += 1

        self.tricks_played_this_round += 1
        self.last_trick_winner_id = winner_id
        self.last_completed_trick = {
            "winner_id": winner_id,
            "winner_name": winner.name,
            "plays": [
                {"player_id": tp.player_id, "card": card_to_dict(tp.card)}
                for tp in self.current_trick
            ],
        }
        self.current_trick = []

        if self.tricks_played_this_round == self.round_number:
            self._finish_round()
        else:
            self.current_player_index = self._index_of(winner_id)

    def _finish_round(self) -> None:
        for p in self.players:
            points = score_round(bid=p.bid or 0, tricks=p.tricks_this_round)
            p.total_score += points
            p.scores_per_round.append(points)

        if self.round_number >= self.total_rounds():
            self.phase = Phase.GAME_OVER
            return

        self.phase = Phase.ROUND_DONE
        self.start_player_index = (self.start_player_index + 1) % len(self.players)

    def start_next_round(self) -> None:
        if self.phase is not Phase.ROUND_DONE:
            raise GameError("Runde noch nicht fertig.")
        self._start_next_round()

    # ---- Helpers ----

    def _player_by_id(self, player_id: str) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise GameError(f"Unbekannter Spieler: {player_id}")

    def _index_of(self, player_id: str) -> int:
        for i, p in enumerate(self.players):
            if p.id == player_id:
                return i
        raise GameError(f"Unbekannter Spieler: {player_id}")

    def current_player(self) -> Optional[Player]:
        if not self.players:
            return None
        return self.players[self.current_player_index]

    def public_state(self) -> dict:
        lead_suit = lead_suit_from_plays([tp.card for tp in self.current_trick])
        return {
            "phase": self.phase.value,
            "round": self.round_number,
            "total_rounds": self.total_rounds(),
            "trick_of_round": self.tricks_played_this_round + (1 if self.current_trick else 0),
            "tricks_in_round": self.round_number,
            "last_completed_trick": self.last_completed_trick,
            "start_player": (
                self.players[self.start_player_index].id if self.players else None
            ),
            "current_player": self.current_player().id if self.current_player() else None,
            "trump_suit": self.trump_suit.value if self.trump_suit else None,
            "trump_card": card_to_dict(self.trump_card) if self.trump_card else None,
            "blind_round": self.round_number == 1 and self.phase in (Phase.BIDDING, Phase.PLAYING),
            "lead_suit": lead_suit.value if lead_suit else None,
            "last_trick_winner": self.last_trick_winner_id,
            "forbidden_bid": self.forbidden_last_bid(),
            "current_trick": [
                {"player_id": tp.player_id, "card": card_to_dict(tp.card)}
                for tp in self.current_trick
            ],
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "bid": p.bid,
                    "tricks": p.tricks_this_round,
                    "score": p.total_score,
                    "hand_size": len(p.hand),
                    "scores_per_round": list(p.scores_per_round),
                }
                for p in self.players
            ],
        }

    def hand_for(self, player_id: str) -> list[dict]:
        player = self._player_by_id(player_id)
        if self.round_number == 1 and self.phase in (Phase.BIDDING, Phase.PLAYING):
            return [{"hidden": True} for _ in player.hand]
        return [card_to_dict(c) for c in player.hand]

    def legal_moves_for(self, player_id: str) -> list[dict]:
        """Vom Server berechnete erlaubte Züge — das Frontend nutzt diese Liste
        für die Bedienzwang-Durchsetzung."""
        player = self._player_by_id(player_id)
        if self.phase is not Phase.PLAYING:
            return []
        if self.round_number == 1:
            return []
        if self.players[self.current_player_index].id != player_id:
            return []
        lead_suit = lead_suit_from_plays([tp.card for tp in self.current_trick])
        legal = legal_cards_in_hand(player.hand, lead_suit)
        return [card_to_dict(c) for c in legal]

    def blind_view_for(self, player_id: str) -> dict:
        """Runde 1: Karten aller ANDEREN Spieler. Für den eigenen Spieler leer."""
        if self.round_number != 1 or self.phase not in (Phase.BIDDING, Phase.PLAYING):
            return {}
        out: dict[str, list[dict]] = {}
        for p in self.players:
            if p.id == player_id:
                continue
            out[p.id] = [card_to_dict(c) for c in p.hand]
        return out
