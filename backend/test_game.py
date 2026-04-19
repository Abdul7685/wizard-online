"""Tests für den Wizard-Spielzustand (Hausregeln)."""
from cards import Card, CardType, Suit
from game import GameError, Phase, WizardGame


def setup_game(num_players: int = 4, seed: int = 42) -> WizardGame:
    g = WizardGame(seed=seed)
    for i in range(num_players):
        g.add_player(f"p{i}", f"Spieler{i}")
    g.start_game()
    return g


def test_cannot_start_with_too_few() -> None:
    g = WizardGame(seed=1)
    g.add_player("a", "A")
    g.add_player("b", "B")
    try:
        g.start_game()
    except GameError:
        return
    raise AssertionError("Sollte Fehler werfen bei 2 Spielern.")


def test_start_deals_one_card_per_player() -> None:
    g = setup_game(num_players=4)
    assert g.round_number == 1
    for p in g.players:
        assert len(p.hand) == 1


def test_total_rounds() -> None:
    assert setup_game(3).total_rounds() == 20
    assert setup_game(4).total_rounds() == 15
    assert setup_game(6).total_rounds() == 10


def test_no_choose_trump_phase() -> None:
    """Hausregel: Kein Geber wählt Trumpf. Phase springt direkt zum Bieten."""
    for seed in range(20):
        g = setup_game(num_players=4, seed=seed)
        assert g.phase is Phase.BIDDING


def test_wizard_revealed_means_no_trump() -> None:
    """Finde einen Seed, wo ein Wizard als Trumpfkarte auftaucht."""
    for seed in range(200):
        g = setup_game(num_players=4, seed=seed)
        if g.trump_card and g.trump_card.type is CardType.WIZARD:
            assert g.trump_suit is None, "Wizard darf kein Trumpf ergeben."
            return
    raise AssertionError("Kein Wizard-Seed gefunden.")


def test_jester_revealed_means_no_trump() -> None:
    for seed in range(200):
        g = setup_game(num_players=4, seed=seed)
        if g.trump_card and g.trump_card.type is CardType.JESTER:
            assert g.trump_suit is None
            return
    raise AssertionError("Kein Narr-Seed gefunden.")


def test_last_round_no_trump() -> None:
    g = WizardGame(seed=1)
    for i in range(6):
        g.add_player(f"p{i}", f"Spieler{i}")
    g.start_game()
    # 6 Spieler -> 10 Runden. Letzte Runde alle 60 Karten verteilt, kein Trumpf.
    for target_round in range(1, g.total_rounds() + 1):
        if target_round == g.total_rounds():
            assert g.trump_card is None, f"Letzte Runde sollte keine Trumpfkarte haben (Runde {target_round})"
            assert g.trump_suit is None
        # Spiel einer Runde durchziehen, ohne tatsächlich zu spielen wäre komplex —
        # wir brechen nach der ersten Prüfung ab, wenn wir in der letzten Runde sind.
        if target_round == g.total_rounds():
            break
        _run_quick_round(g)


def _run_quick_round(g: WizardGame) -> None:
    """Hilft Tests: spiele Runde mit 0-Tipps und erste legale Karte."""
    for _ in range(len(g.players)):
        pid = g.current_player().id
        forbidden = g.forbidden_last_bid()
        bid = 0
        if forbidden == 0:
            bid = 1 if g.round_number >= 1 else 0
        g.place_bid(pid, bid)

    for _ in range(g.round_number):
        for _ in range(len(g.players)):
            pid = g.current_player().id
            player = next(p for p in g.players if p.id == pid)
            from cards import lead_suit_from_plays, legal_cards_in_hand
            lead = lead_suit_from_plays([tp.card for tp in g.current_trick])
            legal = legal_cards_in_hand(player.hand, lead)
            g.play_card(pid, legal[0])

    if g.phase is Phase.ROUND_DONE:
        g.start_next_round()


def test_bidding_order_starts_at_start_player() -> None:
    g = setup_game(num_players=4, seed=3)
    first_bidder = g.current_player().id
    assert first_bidder == g.players[g.start_player_index].id


def test_start_player_rotates_each_round() -> None:
    g = setup_game(num_players=4, seed=7)
    start_ids = [g.players[g.start_player_index].id]
    for _ in range(3):
        _run_quick_round(g)
        if g.phase is Phase.GAME_OVER:
            break
        start_ids.append(g.players[g.start_player_index].id)
    assert len(start_ids) == len(set(start_ids)), "Startspieler soll rotieren."


def test_last_bidder_cannot_match_round_sum() -> None:
    g = setup_game(num_players=3, seed=5)
    g.place_bid(g.current_player().id, 1)
    g.place_bid(g.current_player().id, 0)
    # Summe bisher = 1, Runde = 1, letzter darf nicht 0 tippen.
    assert g.forbidden_last_bid() == 0
    try:
        g.place_bid(g.current_player().id, 0)
    except GameError:
        g.place_bid(g.current_player().id, 1)
        assert g.phase is Phase.PLAYING
        return
    raise AssertionError("Tipp-Zwang wurde nicht durchgesetzt.")


def test_full_round_1() -> None:
    g = setup_game(num_players=4, seed=11)

    # Runde 1: alle tippen 0, außer letztem — Tipp-Zwang verhindert 0 wenn Summe = 1 erreicht würde.
    # Bei Tipp 0,0,0 ist Summe = 0, letzter darf 0 tippen (Summe wäre dann 0, nicht 1). OK.
    bids = [0, 0, 0, 0]
    # Wir müssen prüfen: letzter Tipp darf nicht Runde=1 erreichen
    # Summe nach 3 Bids = 0, Runde = 1, verboten = 1. 0 ist erlaubt.
    for _ in range(4):
        g.place_bid(g.current_player().id, 0)

    assert g.phase is Phase.PLAYING

    from cards import lead_suit_from_plays, legal_cards_in_hand
    for _ in range(4):
        pid = g.current_player().id
        player = next(p for p in g.players if p.id == pid)
        lead = lead_suit_from_plays([tp.card for tp in g.current_trick])
        legal = legal_cards_in_hand(player.hand, lead)
        g.play_card(pid, legal[0])

    assert g.phase in (Phase.ROUND_DONE, Phase.GAME_OVER)
    total_tricks = sum(p.tricks_this_round for p in g.players)
    assert total_tricks == 1


def test_blind_round_1_hand_hidden() -> None:
    g = setup_game(num_players=4, seed=1)
    pid = g.players[0].id
    hand = g.hand_for(pid)
    assert len(hand) == 1
    assert hand[0] == {"hidden": True}


def test_blind_round_1_sees_other_hands() -> None:
    g = setup_game(num_players=4, seed=1)
    pid = g.players[0].id
    view = g.blind_view_for(pid)
    assert set(view.keys()) == {p.id for p in g.players if p.id != pid}
    for cards in view.values():
        assert len(cards) == 1


def test_round_2_hand_is_visible() -> None:
    g = setup_game(num_players=3, seed=5)
    _run_quick_round(g)
    assert g.round_number == 2
    pid = g.players[0].id
    hand = g.hand_for(pid)
    assert len(hand) == 2
    for card in hand:
        assert "type" in card


def test_cannot_play_wizard_when_has_lead_suit() -> None:
    """End-to-End: im echten Spiel greift die Hausregel."""
    g = WizardGame(seed=0)
    for i in range(3):
        g.add_player(f"p{i}", f"S{i}")
    # Manipulieren wir die Hand für den Test
    g.phase = Phase.PLAYING
    g.round_number = 3
    g.current_player_index = 0
    g.start_player_index = 0
    red_card = Card(CardType.NUMBER, Suit.RED, 5)
    g.players[0].hand = [red_card, Card(CardType.WIZARD)]
    g.players[1].hand = [Card(CardType.NUMBER, Suit.RED, 10)]
    g.players[2].hand = [Card(CardType.NUMBER, Suit.BLUE, 3)]
    # Spieler 1 führt ein: Rot 7 gespielt (simuliert)
    g.current_trick = [type(g.current_trick[0] if g.current_trick else None)] if False else []
    from game import TrickPlay
    g.current_trick.append(TrickPlay(player_id="other", card=Card(CardType.NUMBER, Suit.RED, 7)))
    g.current_player_index = 0

    # Spieler 0 hat Rot — darf keinen Wizard spielen
    try:
        g.play_card("p0", Card(CardType.WIZARD))
    except GameError:
        return
    raise AssertionError("Wizard bei Bedienpflicht sollte nicht erlaubt sein.")


def test_public_state_has_no_hands() -> None:
    g = setup_game(num_players=4)
    state = g.public_state()
    for p in state["players"]:
        assert "hand" not in p
        assert "hand_size" in p


def test_public_state_has_blind_round_flag() -> None:
    g = setup_game(num_players=4)
    state = g.public_state()
    assert state["blind_round"] is True
    assert state["round"] == 1


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"OK  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} Tests bestanden.")
