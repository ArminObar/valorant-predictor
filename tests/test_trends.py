"""Phase-1 Trends (ASSUMPTIONS §61): store-derived team form windows.
Pins the metric definitions, the window/activity/lifetime filters, and
the null behavior for inputs the store does not hold."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vpredict import config
from vpredict.data.schema import (Match, MapResult, PlayerMapStats,
                                  RoundResult)
from vpredict.data.trends import build_trends

NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


def _players(kills, fk=0, fd=0, agent="Jett"):
    return [PlayerMapStats(name=f"p{i}", agent=agent, kills=kills,
                           fk=fk if i == 0 else 0,
                           fd=fd if i == 0 else 0) for i in range(5)]


def _map(t1=13, t2=7, rounds=None, k1=15, k2=10, fk=3, fd=1):
    return MapResult(game_id="g", map_name="Bind", index=1,
                     team1_score=t1, team2_score=t2,
                     rounds=rounds or [], team1_players=_players(k1, fk, fd),
                     team2_players=_players(k2))


def _match(i, days_ago, maps, a=("A", "Team A"), b=("B", "Team B")):
    return Match(match_id=f"m{i}", start_ts=NOW - timedelta(days=days_ago),
                 status="completed", best_of=3, event="ev", series="s",
                 team1_id=a[0], team1_name=a[1], team2_id=b[0],
                 team2_name=b[1], winner="team1", maps=maps)


def _rounds():
    r = [RoundResult(number=1, winner="team1", side="attack",
                     win_method="elim"),
         RoundResult(number=2, winner="team2", side="defense",
                     win_method="boom"),
         RoundResult(number=13, winner="team2", side="attack",
                     win_method="defuse")]
    return r


def test_metric_definitions_pin_exactly():
    ms = [_match(i, days_ago=5 + i, maps=[_map(rounds=_rounds())])
          for i in range(6)]
    rep = build_trends(ms, now=NOW)
    row = {r["team_id"]: r for r in rep["teams"]}["A"]
    assert row["n_lifetime"] == 6 and row["n_window"] == 6
    assert row["win_rate"] == 1.0                    # 13-7 every map
    assert row["spread_avg"] == pytest.approx(6.0)
    # Team A won pistol round 1, lost round 13, every map.
    assert row["pistol_wr"] == pytest.approx(0.5)
    # 5 players x (15 + 10) kills combined.
    assert row["comb_kills_avg"] == pytest.approx(125.0)
    # (fk - fd) = 2 per 20 rounds -> 1.2 per 12.
    assert row["fk_diff12"] == pytest.approx(1.2)
    # The only WON round with a method is round 1 (elim).
    assert row["method_mix"] == {"elim": 1.0, "boom": 0.0,
                                 "defuse": 0.0, "time": 0.0}
    assert row["agents_top"][0] == {"agent": "Jett", "n": 30}


def test_window_uses_only_the_last_n_maps(monkeypatch):
    monkeypatch.setattr(config, "TRENDS_WINDOW_MAPS", 2)
    old = [_match(i, days_ago=30 - i, maps=[_map(t1=0, t2=13)])
           for i in range(4)]
    recent = [_match(9, days_ago=1, maps=[_map(t1=13, t2=0),
                                          _map(t1=13, t2=0)])]
    rep = build_trends(old + recent, now=NOW)
    row = {r["team_id"]: r for r in rep["teams"]}["A"]
    assert row["n_window"] == 2 and row["win_rate"] == 1.0
    assert row["spread_avg"] == pytest.approx(13.0)


def test_activity_and_lifetime_filters():
    stale = [_match(i, days_ago=200 + i, maps=[_map()],
                    a=("OLD", "Old Org"), b=("B", "Team B"))
             for i in range(6)]
    thin = [_match(50, days_ago=2, maps=[_map()],
                   a=("NEW", "New Org"), b=("B", "Team B"))]
    rep = build_trends(stale + thin, now=NOW)
    ids = {r["team_id"] for r in rep["teams"]}
    assert "OLD" not in ids        # no completed map inside active_days
    assert "NEW" not in ids        # under min lifetime maps
    assert "B" in ids              # 7 maps, latest 2 days ago


def test_missing_inputs_yield_null_not_estimates():
    ms = [_match(i, days_ago=3 + i, maps=[_map(rounds=[])])
          for i in range(5)]
    row = {r["team_id"]: r
           for r in build_trends(ms, now=NOW)["teams"]}["A"]
    assert row["pistol_wr"] is None        # no round strip, no pistols
    assert row["method_mix"] is None       # no won-round methods known
