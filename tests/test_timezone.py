"""Timezone regression tests (LOG entry 29).

vlr.gg's `data-utc-ts` is the site's US-Eastern wall clock, not UTC. These
tests pin the fix at both layers: the parser converts ET wall time to true
UTC (DST-aware), and the one-time store/ledger migration shifts existing
rows exactly once, keeps the store's sort invariant across the DST seam,
and never touches a frozen prediction's probabilities or made_at.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from vpredict.data.migrate import migrate_tz_if_needed
from vpredict.data.schema import Match
from vpredict.data import store
from vpredict.scraping.parse_match import _parse_utc_ts
from vpredict.serving.ledger import Ledger


def _soup(attr: str) -> BeautifulSoup:
    return BeautifulSoup(
        f'<div class="moment-tz-convert" data-utc-ts="{attr}">x</div>', "lxml")


def test_parser_treats_attr_as_eastern_wall_time_edt():
    # The live-site case: attribute 04:00 on 2026-07-24 (EDT, UTC-4)
    # is really 08:00 UTC.
    got = _parse_utc_ts(_soup("2026-07-24 04:00:00"))
    assert got == datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)


def test_parser_treats_attr_as_eastern_wall_time_est():
    # Winter dates carry the EST offset (UTC-5), not a fixed 4 h.
    got = _parse_utc_ts(_soup("2026-01-10 15:00:00"))
    assert got == datetime(2026, 1, 10, 20, 0, tzinfo=timezone.utc)


def _mk(mid: str, start: datetime, status: str = "completed") -> Match:
    return Match(match_id=mid, start_ts=start, status=status)


def test_migration_shifts_resorts_and_runs_once(tmp_path):
    matches = tmp_path / "matches.jsonl"
    marker = tmp_path / ".tz_migration_v1.json"
    ledger_path = tmp_path / "ledger.sqlite"

    # Two mislabeled rows straddling the Nov 2025 fall-back: the EDT row
    # shifts +4 h, the EST row +5 h, so their order can only survive if the
    # migration re-sorts (the store's (start_ts, match_id) invariant).
    edt = datetime(2025, 10, 25, 23, 30, tzinfo=timezone.utc)   # -> +4 h
    est = datetime(2025, 11, 2, 3, 0, tzinfo=timezone.utc)      # -> +5 h
    store.upsert_matches([_mk("a", edt), _mk("b", est)], matches)

    led = Ledger(ledger_path)
    start = datetime(2026, 7, 24, 4, 0, tzinfo=timezone.utc)    # mislabeled
    led.insert_prediction(
        match_id="m1", start_ts=start, team1="1", team2="2",
        team1_name="A", team2_name="B", event="E", best_of=3,
        p_model=0.7692, p_elo=0.7196, model_version="v",
        now=start - timedelta(hours=1))
    made_at_before = led.rows()[0]["made_at"]
    led.close()

    rep = migrate_tz_if_needed(matches_path=matches,
                               upcoming_path=tmp_path / "none.jsonl",
                               ledger_path=ledger_path, marker=marker)
    assert rep["n_matches"] == 2 and rep["n_ledger_rows"] == 1
    assert marker.exists()

    got = store.load_matches(matches)
    by_id = {m.match_id: m.start_ts for m in got}
    assert by_id["a"] == datetime(2025, 10, 26, 3, 30, tzinfo=timezone.utc)
    assert by_id["b"] == datetime(2025, 11, 2, 8, 0, tzinfo=timezone.utc)
    starts = [(m.start_ts, m.match_id) for m in got]
    assert starts == sorted(starts)          # invariant held after the shift

    led = Ledger(ledger_path)
    row = led.rows()[0]
    fixed = datetime.fromisoformat(row["start_ts"])
    assert fixed == datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
    # The frozen record is otherwise untouched — probabilities and made_at
    # are the public commitments; only the match-metadata start moved.
    assert row["p_model"] == 0.7692 and row["p_elo"] == 0.7196
    assert row["made_at"] == made_at_before
    led.close()

    # Second call: marker makes it a no-op — a double shift would corrupt.
    rep2 = migrate_tz_if_needed(matches_path=matches,
                                upcoming_path=tmp_path / "none.jsonl",
                                ledger_path=ledger_path, marker=marker)
    assert rep2 == json.loads(marker.read_text())
    assert {m.match_id: m.start_ts for m in store.load_matches(matches)} == by_id
