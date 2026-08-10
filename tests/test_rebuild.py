"""Rebuild-from-raw (ASSUMPTIONS §67): raw bodies replay through the
production parser and linker into exactly the freeze/close rows the
original loop would have appended, restricted to before the surviving
log's head, suspended rows gated, existing rows deduped."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from vpredict.odds.rebuild import candidates_from_raw, _key
from vpredict.odds.schema import OddsCapture

START = datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 7, 29, 19, 38, tzinfo=timezone.utc)

ROWS = [{"match_id": "m1", "team1_name": "Team Alpha",
         "team2_name": "Team Beta", "start_ts": START.isoformat()},
        {"match_id": "m2", "team1_name": "Gamma", "team2_name": "Delta",
         "start_ts": (START + timedelta(days=5)).isoformat()}]


def _body(home, away, ph, pa, start=START, status="TRADING"):
    return {"events": [{
        "id": 9001, "status": status,
        "home": {"name": home}, "away": {"name": away},
        "startTime": start.isoformat(),
        "markets": {"esports.valorant.winner": {"submarkets": {
            "period=ot&period=regulation": {"selections": [
                {"outcome": "home", "price": ph},
                {"outcome": "away", "price": pa}]}}}}}]}


def _raw(days_before_start, ph=1.8, pa=2.0, home="Team Alpha",
         away="Team Beta", start=START):
    t = start - timedelta(days=days_before_start)
    return (t, _body(home, away, ph, pa, start=start))


def test_lost_head_replays_into_freeze_then_close():
    raw = [_raw(3.0),                       # first sighting -> freeze
           _raw(1.0),                       # mid-window -> no slot, skip
           _raw(days_before_start=10 / (24 * 60))]   # 10 min out -> close
    got = candidates_from_raw(raw, ROWS, {}, CUTOFF)
    assert [(c.capture_kind, c.match_id) for c in got] == \
        [("freeze", "m1"), ("close", "m1")]
    assert got[0].captured_at == START - timedelta(days=3)
    assert got[0].book_home_is_team1 is True
    assert got[0].link_method == "exact"


def test_cutoff_excludes_surviving_window_and_key_dedupe_belts():
    raw = [_raw(3.0),
           (CUTOFF + timedelta(hours=1),
            _body("Team Alpha", "Team Beta", 1.9, 1.9))]
    got = candidates_from_raw(raw, ROWS, {}, CUTOFF)
    assert len(got) == 1                       # post-cutoff row excluded
    keyed = candidates_from_raw([_raw(3.0)], ROWS, {}, CUTOFF,
                                existing_keys={_key(got[0])})
    assert keyed == []                         # already-present row deduped


def test_suspended_rows_are_gated_not_resynthesized():
    raw = [_raw(3.0, ph=0.0, pa=0.0), _raw(2.5)]
    got = candidates_from_raw(raw, ROWS, {}, CUTOFF)
    assert [(c.capture_kind, float(c.price_home)) for c in got] == \
        [("freeze", 1.8)]                      # 0.0 dropped, real row kept


def test_unlinked_fixtures_stay_out_of_scope():
    raw = [_raw(3.0, home="Nobody FC", away="Unknown Org")]
    assert candidates_from_raw(raw, ROWS, {}, CUTOFF) == []


def test_started_matches_get_nothing():
    raw = [(START + timedelta(hours=1),
            _body("Team Alpha", "Team Beta", 1.5, 2.5))]
    assert candidates_from_raw(raw, ROWS, {}, CUTOFF + timedelta(days=2)) \
        == []
