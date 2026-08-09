"""Roster-continuity Phase 1 (ASSUMPTIONS §66): membership-only features,
as-of by estimated finish, batch sweep pinned equal to the serving query,
and the cold-start signal it exists for."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vpredict.data import store
from vpredict.data.schema import Match, MapResult, PlayerMapStats
from vpredict.features.roster import (roster_continuity_table,
                                      roster_features_asof)
from vpredict.modeling.baselines import matches_lite_from_maps

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _m(mid, days_ago, t1, t2, l1, l2, best_of=3):
    def _pl(names):
        return [PlayerMapStats(name=n, agent="Jett", kills=10, fk=1, fd=1)
                for n in names]
    st = NOW - timedelta(days=days_ago)
    return Match(match_id=mid, start_ts=st, status="completed",
                 best_of=best_of, event="E", series="s", winner="team1",
                 team1_id=t1, team1_name=t1, team2_id=t2, team2_name=t2,
                 maps=[MapResult(game_id=f"{mid}-1", map_name="Bind",
                                 index=1, team1_score=13, team2_score=7,
                                 rounds=[], team1_players=_pl(l1),
                                 team2_players=_pl(l2))])


VETS = ["v1", "v2", "v3", "v4", "v5"]


def _history():
    ms = []
    # The veterans play 6 maps together on OldOrg against rotating filler.
    for i in range(6):
        ms.append(_m(f"h{i}", 60 - i, "OldOrg", f"F{i}",
                     VETS, [f"x{i}{j}" for j in range(5)]))
    return ms


def test_new_team_of_veterans_beats_new_team_of_unknowns():
    ms = _history()
    # Two debuts: NewVets fields the OldOrg five; NewKids five unknowns.
    ms.append(_m("d1", 10, "NewVets", "F9", VETS,
                 [f"z{j}" for j in range(5)]))
    ms.append(_m("d2", 10, "NewKids", "F8",
                 [f"k{j}" for j in range(5)],
                 [f"y{j}" for j in range(5)]))
    df = store.maps_frame(ms)
    cutoff = NOW.replace(tzinfo=timezone.utc)
    vets = roster_features_asof(df, "NewVets", cutoff)
    kids = roster_features_asof(df, "NewKids", cutoff)
    # Imported experience: the veterans carry OldOrg history; a roster
    # of never-seen names carries exactly zero. That zero is the intended
    # semantics — the debut of true unknowns stays at defaults.
    assert vets["roster_ext_maps_log"] > 0.0
    assert kids["roster_ext_maps_log"] == 0.0
    # Co-play: vets share 7 prior maps; the kids share only their own
    # debut map (log1p(1)).
    assert vets["roster_coplay_log"] > kids["roster_coplay_log"]
    assert kids["roster_coplay_log"] == pytest.approx(0.6931, abs=1e-3)


def test_asof_excludes_maps_finishing_after_cutoff():
    ms = _history()
    df = store.maps_frame(ms)
    # Cutoff BEFORE the estimated finish of the most recent history map
    # (starts 55 days ago, Bo3 -> +3h): one map must not count yet.
    last_start = NOW - timedelta(days=55)
    before = roster_features_asof(df, "OldOrg",
                                  last_start + timedelta(hours=1))
    after = roster_features_asof(df, "OldOrg",
                                 last_start + timedelta(hours=4))
    assert after["roster_coplay_log"] > before["roster_coplay_log"]


def test_ext_maps_counts_only_other_teams():
    ms = _history()
    df = store.maps_frame(ms)
    # OldOrg's five have played ONLY on OldOrg: zero imported experience.
    got = roster_features_asof(df, "OldOrg", NOW)
    assert got["roster_ext_maps_log"] == 0.0
    assert got["roster_coplay_log"] > 0.0


def test_debut_team_without_any_eligible_map_reads_zero():
    df = store.maps_frame(_history())
    got = roster_features_asof(df, "NeverSeen", NOW)
    assert got == {"roster_ext_maps_log": 0.0, "roster_coplay_log": 0.0}


def test_batch_sweep_matches_the_serving_query_exactly():
    ms = _history()
    ms.append(_m("d1", 10, "NewVets", "F9", VETS,
                 [f"z{j}" for j in range(5)]))
    df = store.maps_frame(ms)
    lites = matches_lite_from_maps(df)
    table = roster_continuity_table(df, lites)
    for lite in lites:
        for side in ("a", "b"):
            batch = table[(str(lite["match_id"]), lite[side])]
            solo = roster_features_asof(df, lite[side], lite["start_ts"])
            assert batch == solo, (lite["match_id"], side)
