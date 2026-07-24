"""Odds capture — offline validation (the sandbox cannot reach any book).

De-vig math is exact and property-tested; parsers run against fixtures
shaped from Cloudbet's published response samples and the assumed Pinnacle
guest-API shapes. The first LIVE run happens on the owner's Mac (LOG entry
25's protocol) — these tests pin everything that can be pinned offline.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vpredict.odds import cloudbet, devig
from vpredict.odds.pinnacle import american_to_decimal, parse_intercepts
from vpredict.odds.schema import (OddsCapture, append_captures,
                                  capture_state, iter_captures, link_fixture)

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


# -------------------------------------------------------------------- devig

def test_devig_symmetric_prices_give_half_half():
    for method in (devig.devig_shin, devig.devig_multiplicative):
        p = method([1.90, 1.90])
        assert p[0] == pytest.approx(0.5, abs=1e-9)
        assert sum(p) == pytest.approx(1.0, abs=1e-9)


def test_devig_fair_odds_pass_through():
    p = devig.devig_shin([2.0, 2.0])
    assert p == pytest.approx([0.5, 0.5], abs=1e-9)
    assert devig.overround([2.0, 2.0]) == pytest.approx(0.0, abs=1e-12)


def test_shin_shifts_toward_favourite_vs_multiplicative():
    odds = [1.30, 3.50]
    mult = devig.devig_multiplicative(odds)
    shin = devig.devig_shin(odds)
    assert sum(shin) == pytest.approx(1.0, abs=1e-9)
    assert shin[0] > mult[0]          # favourite gains under Shin
    assert shin[1] < mult[1]          # longshot loses the extra margin
    assert mult[0] == pytest.approx((1 / 1.30) / (1 / 1.30 + 1 / 3.50))


def test_devig_rejects_impossible_odds():
    with pytest.raises(ValueError):
        devig.implied([0.95, 2.0])


def test_devig_both_reports_all_columns():
    out = devig.devig_both([1.80, 2.10])
    assert set(out) == {"implied", "overround", "shin", "multiplicative"}
    assert out["overround"] > 0


# ---------------------------------------------------------- schema + state

def _cap(mid, kind, source="cloudbet", event="e1"):
    return OddsCapture(
        captured_at=NOW, source=source, capture_kind=kind,
        book_event_id=event, book_home="Team Solid", book_away="Krunker",
        price_home=1.60, price_away=2.30, match_id=mid)


def test_append_iter_roundtrip_and_state(tmp_path, monkeypatch):
    path = tmp_path / "odds.jsonl"
    assert append_captures([_cap("m1", "freeze")], path=path) == 1
    assert append_captures([_cap("m1", "close"),
                            _cap(None, "freeze", event="e9")], path=path) == 2
    got = list(iter_captures(path))
    assert [c.capture_kind for c in got] == ["freeze", "close", "freeze"]
    state = capture_state(path)
    assert state[("cloudbet", "m1")] == {"freeze": True, "close": True}
    assert state[("cloudbet", "book:e9")] == {"freeze": True, "close": False}


# ------------------------------------------------------------------ linking

PREDS = [{"match_id": "m1", "team1_name": "Team Solid",
          "team2_name": "Krunker Esports", "start_ts": "2026-07-25T12:00:00Z"}]


def test_link_exact_both_orientations():
    mid, home_is_t1, method = link_fixture("Team Solid", "Krunker Esports",
                                           PREDS)
    assert (mid, home_is_t1, method) == ("m1", True, "exact")
    mid, home_is_t1, method = link_fixture("KRUNKER ESPORTS", "team solid.",
                                           PREDS)
    assert (mid, home_is_t1, method) == ("m1", False, "exact")


def test_link_alias_and_unlinked():
    aliases = {"krnkr": "krunkeresports"}
    mid, home_is_t1, method = link_fixture("Team Solid", "KRNKR", PREDS,
                                           aliases)
    assert (mid, home_is_t1, method) == ("m1", True, "alias")
    assert link_fixture("Totally Other", "Nobody", PREDS) == (None, None, None)


# ----------------------------------------------------------------- cloudbet

CB_PAYLOAD = {
    "events": [
        {   # normal series with winner + a handicap market to be ignored
            "id": 777, "status": "TRADING",
            "home": {"name": "Team Solid"}, "away": {"name": "Krunker"},
            "startTime": "2026-07-25T12:00:00Z",
            "markets": {
                "esport-valorant.winner": {"submarkets": {"period=ft": {
                    "selections": [
                        {"outcome": "home", "params": "", "price": 1.61,
                         "side": "BACK"},
                        {"outcome": "away", "params": "", "price": 2.29,
                         "side": "BACK"}]}}},
                "esport-valorant.handicap": {"submarkets": {"period=ft": {
                    "selections": [
                        {"outcome": "home", "params": "handicap=-1.5",
                         "price": 2.4, "side": "BACK"}]}}},
            },
        },
        {   # outright-style event: no home/away -> skipped
            "id": 778, "status": "TRADING", "home": None, "away": None,
            "markets": {"esport-valorant.outright": {"submarkets": {}}},
        },
    ]
}


def test_cloudbet_parse_extracts_winner_and_reports_keys():
    caps, keys = cloudbet.parse_competition_events(CB_PAYLOAD, NOW, "freeze")
    assert len(caps) == 1
    c = caps[0]
    assert (c.book_home, c.book_away) == ("Team Solid", "Krunker")
    assert (c.price_home, c.price_away) == (1.61, 2.29)
    assert c.book_market_key == "esport-valorant.winner"
    assert "esport-valorant.handicap" in keys        # visibility for LOG


def test_cloudbet_winner_market_requires_both_sides():
    broken = {"events": [{**CB_PAYLOAD["events"][0], "markets": {
        "esport-valorant.winner": {"submarkets": {"p": {"selections": [
            {"outcome": "home", "params": "", "price": 1.5, "side": "BACK"}
        ]}}}}}]}
    caps, _ = cloudbet.parse_competition_events(broken, NOW, "freeze")
    assert caps == []


# ----------------------------------------------------------------- pinnacle

def test_american_to_decimal():
    assert american_to_decimal(150) == pytest.approx(2.5)
    assert american_to_decimal(-200) == pytest.approx(1.5)
    with pytest.raises(ValueError):
        american_to_decimal(50)


def test_pinnacle_parse_joins_matchups_and_prices():
    bodies = [
        {"url": ".../matchups", "json": [
            {"id": 42, "startTime": "2026-07-25T12:00:00Z",
             "participants": [{"alignment": "home", "name": "Team Solid"},
                              {"alignment": "away", "name": "Krunker"}]}]},
        {"url": ".../markets/straight", "json": [
            {"matchupId": 42, "type": "moneyline", "period": 0,
             "prices": [{"designation": "home", "price": -150},
                        {"designation": "away", "price": 130}]}]},
    ]
    caps = parse_intercepts(bodies, NOW, "freeze")
    assert len(caps) == 1
    c = caps[0]
    assert c.price_home == pytest.approx(1.6667, abs=1e-3)
    assert c.price_away == pytest.approx(2.30, abs=1e-9)


def test_pinnacle_unrecognised_shapes_parse_to_nothing():
    assert parse_intercepts([{"url": "x", "json": {"whatever": 1}}],
                            NOW, "freeze") == []


# --------------------------------------------------- capture state machine

def test_decide_kind_freeze_then_close_then_done():
    from scripts.capture_odds import decide_kind
    start = NOW + timedelta(hours=3)
    slot = {"freeze": False, "close": False}
    assert decide_kind(start, slot, NOW) == "freeze"
    slot["freeze"] = True
    assert decide_kind(start, slot, NOW) is None            # outside window
    near = start - timedelta(minutes=10)
    assert decide_kind(start, slot, near) == "close"
    slot["close"] = True
    assert decide_kind(start, slot, near) is None
    assert decide_kind(start, slot, start + timedelta(minutes=1)) is None
