from fetchers._base import carry_enrichment


def test_copies_missing_fields_from_loser():
    winner = {"source": "local", "steam_review_percent": None, "coop_online": False}
    loser = {"source": "api", "steam_review_percent": 90, "coop_online": True, "hltb_main_hours": 3.0}
    out = carry_enrichment(winner, loser)
    assert out["steam_review_percent"] == 90
    assert out["coop_online"] is True
    assert out["hltb_main_hours"] == 3.0
    assert out["source"] == "local"


def test_does_not_clobber_winner_values():
    winner = {"steam_review_percent": 95, "coop_online": True}
    loser = {"steam_review_percent": 70, "coop_online": False}
    out = carry_enrichment(winner, loser)
    assert out["steam_review_percent"] == 95
    assert out["coop_online"] is True


def test_no_loser_returns_winner():
    winner = {"name": "X"}
    assert carry_enrichment(winner, None) is winner
