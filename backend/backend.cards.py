"""Wizard-Kartenspiel: Karten, Deck, Stich-Logik."""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Suit(str, Enum):
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    BLUE = "blue"


class CardType(str, Enum):
    NUMBER = "number"
    WIZARD = "wizard"
    JESTER = "jester"


@dataclass(frozen=True)
class Card:
    type: CardType
    suit: Optional[Suit] = None
    value: Optional[int] = None

    def __str__(self) -> str:
        if self.type is CardType.WIZARD:
            return "Z"
        if self.type is CardType.JESTER:
            return "N"
        return f"{self.value}{self.suit.value[0].upper()}"


def build_deck() -> list[Card]:
    deck: list[Card] = []
    for suit in Suit:
        for value in range(1, 14):
            deck.append(Card(CardType.NUMBER, suit, value))
    for _ in range(4):
        deck.append(Card(CardType.WIZARD))
        deck.append(Card(CardType.JESTER))
    return deck


def shuffled_deck(rng: Optional[random.Random] = None) -> list[Card]:
    deck = build_deck()
    (rng or random).shuffle(deck)
    return deck


def trick_winner(
    plays: list[Card],
    trump: Optional[Suit],
) -> int:
    """Return index (0-based) of the winning play in `plays`.

    Rules:
    - First Wizard in the trick wins.
    - Otherwise highest trump wins.
    - Otherwise highest card of the lead suit wins.
    - Only Jesters -> first Jester wins.
    - Lead suit is the suit of the first non-Jester, non-Wizard card.
      If the opener played a Wizard, no suit has to be followed.
    """
    for i, card in enumerate(plays):
        if card.type is CardType.WIZARD:
            return i

    lead_suit: Optional[Suit] = None
    for card in plays:
        if card.type is CardType.NUMBER:
            lead_suit = card.suit
            break

    if lead_suit is None:
        return 0

    best_idx = -1
    best_value = -1
    best_is_trump = False

    for i, card in enumerate(plays):
        if card.type is not CardType.NUMBER:
            continue
        is_trump = trump is not None and card.suit == trump
        matches_lead = card.suit == lead_suit

        if not is_trump and not matches_lead:
            continue

        better = False
        if is_trump and not best_is_trump:
            better = True
        elif is_trump == best_is_trump and card.value > best_value:
            better = True

        if better:
            best_idx = i
            best_value = card.value
            best_is_trump = is_trump

    return best_idx


def is_legal_play(
    card: Card,
    hand: list[Card],
    lead_suit: Optional[Suit],
) -> bool:
    """Hausregel: Wenn Bedienfarbe vorhanden und Spieler hat sie, MUSS er sie spielen
    — kein Wizard, kein Narr, kein Trumpf, keine andere Farbe."""
    if card not in hand:
        return False
    if lead_suit is None:
        return True
    has_lead = any(
        c.type is CardType.NUMBER and c.suit == lead_suit for c in hand
    )
    if has_lead:
        return card.type is CardType.NUMBER and card.suit == lead_suit
    return True


def legal_cards_in_hand(
    hand: list[Card],
    lead_suit: Optional[Suit],
) -> list[Card]:
    return [c for c in hand if is_legal_play(c, hand, lead_suit)]


def lead_suit_from_plays(plays: list[Card]) -> Optional[Suit]:
    """Lead suit for followers: first number card's suit.
    If the first card is a Wizard, no suit is led."""
    if not plays:
        return None
    if plays[0].type is CardType.WIZARD:
        return None
    for card in plays:
        if card.type is CardType.NUMBER:
            return card.suit
    return None


def score_round(bid: int, tricks: int) -> int:
    if bid == tricks:
        return 20 + 10 * tricks
    return -10 * abs(bid - tricks)


def card_to_dict(card: Card) -> dict:
    return {
        "type": card.type.value,
        "suit": card.suit.value if card.suit else None,
        "value": card.value,
    }


def card_from_dict(data: dict) -> Card:
    t = CardType(data["type"])
    suit = Suit(data["suit"]) if data.get("suit") else None
    value = data.get("value")
    return Card(type=t, suit=suit, value=value)
