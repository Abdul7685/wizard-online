"""Tests für die Wizard-Karten-Logik (Hausregeln)."""
from cards import (
    Card,
    CardType,
    Suit,
    build_deck,
    is_legal_play,
    lead_suit_from_plays,
    legal_cards_in_hand,
    score_round,
    trick_winner,
)


def test_deck_has_60_cards() -> None:
    deck = build_deck()
    assert len(deck) == 60
    wizards = [c for c in deck if c.type is CardType.WIZARD]
    jesters = [c for c in deck if c.type is CardType.JESTER]
    numbers = [c for c in deck if c.type is CardType.NUMBER]
    assert len(wizards) == 4
    assert len(jesters) == 4
    assert len(numbers) == 52


def test_wizard_always_wins() -> None:
    plays = [
        Card(CardType.NUMBER, Suit.RED, 13),
        Card(CardType.WIZARD),
        Card(CardType.NUMBER, Suit.RED, 12),
    ]
    assert trick_winner(plays, trump=Suit.RED) == 1


def test_first_wizard_wins() -> None:
    plays = [Card(CardType.WIZARD), Card(CardType.WIZARD)]
    assert trick_winner(plays, trump=None) == 0


def test_highest_trump_wins() -> None:
    plays = [
        Card(CardType.NUMBER, Suit.RED, 10),
        Card(CardType.NUMBER, Suit.BLUE, 2),
        Card(CardType.NUMBER, Suit.RED, 5),
    ]
    assert trick_winner(plays, trump=Suit.BLUE) == 1


def test_highest_lead_suit_wins_without_trump() -> None:
    plays = [
        Card(CardType.NUMBER, Suit.RED, 3),
        Card(CardType.NUMBER, Suit.BLUE, 13),
        Card(CardType.NUMBER, Suit.RED, 10),
    ]
    assert trick_winner(plays, trump=Suit.GREEN) == 2


def test_only_jesters_first_wins() -> None:
    plays = [Card(CardType.JESTER), Card(CardType.JESTER)]
    assert trick_winner(plays, trump=Suit.RED) == 0


def test_jester_leads_then_number_defines_suit() -> None:
    plays = [
        Card(CardType.JESTER),
        Card(CardType.NUMBER, Suit.GREEN, 5),
        Card(CardType.NUMBER, Suit.GREEN, 9),
    ]
    assert trick_winner(plays, trump=None) == 2


def test_must_follow_lead_suit() -> None:
    hand = [
        Card(CardType.NUMBER, Suit.RED, 5),
        Card(CardType.NUMBER, Suit.BLUE, 7),
    ]
    red = Card(CardType.NUMBER, Suit.RED, 5)
    blue = Card(CardType.NUMBER, Suit.BLUE, 7)
    assert is_legal_play(red, hand, Suit.RED)
    assert not is_legal_play(blue, hand, Suit.RED)


def test_wizard_forbidden_when_lead_suit_held() -> None:
    """Hausregel: Wizard/Narr sind verboten, wenn der Spieler die Bedienfarbe hat."""
    hand = [Card(CardType.NUMBER, Suit.RED, 5), Card(CardType.WIZARD), Card(CardType.JESTER)]
    assert not is_legal_play(Card(CardType.WIZARD), hand, Suit.RED)
    assert not is_legal_play(Card(CardType.JESTER), hand, Suit.RED)
    assert is_legal_play(Card(CardType.NUMBER, Suit.RED, 5), hand, Suit.RED)


def test_wizard_allowed_when_no_lead_suit_held() -> None:
    hand = [Card(CardType.NUMBER, Suit.BLUE, 5), Card(CardType.WIZARD), Card(CardType.JESTER)]
    assert is_legal_play(Card(CardType.WIZARD), hand, Suit.RED)
    assert is_legal_play(Card(CardType.JESTER), hand, Suit.RED)
    assert is_legal_play(Card(CardType.NUMBER, Suit.BLUE, 5), hand, Suit.RED)


def test_can_play_any_without_lead_suit() -> None:
    hand = [Card(CardType.NUMBER, Suit.BLUE, 7), Card(CardType.WIZARD)]
    assert is_legal_play(Card(CardType.NUMBER, Suit.BLUE, 7), hand, None)
    assert is_legal_play(Card(CardType.WIZARD), hand, None)


def test_legal_cards_in_hand() -> None:
    hand = [
        Card(CardType.NUMBER, Suit.RED, 5),
        Card(CardType.NUMBER, Suit.BLUE, 7),
        Card(CardType.WIZARD),
    ]
    legal = legal_cards_in_hand(hand, Suit.RED)
    assert legal == [Card(CardType.NUMBER, Suit.RED, 5)]

    legal_all = legal_cards_in_hand(hand, Suit.GREEN)
    assert len(legal_all) == 3


def test_score_hit() -> None:
    assert score_round(bid=3, tricks=3) == 50
    assert score_round(bid=0, tricks=0) == 20


def test_score_miss() -> None:
    assert score_round(bid=2, tricks=4) == -20
    assert score_round(bid=5, tricks=2) == -30


def test_lead_suit_from_wizard_opener() -> None:
    plays = [Card(CardType.WIZARD), Card(CardType.NUMBER, Suit.RED, 5)]
    assert lead_suit_from_plays(plays) is None


def test_lead_suit_from_jester_opener() -> None:
    plays = [Card(CardType.JESTER), Card(CardType.NUMBER, Suit.RED, 5)]
    assert lead_suit_from_plays(plays) is Suit.RED


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"OK  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} Tests bestanden.")
