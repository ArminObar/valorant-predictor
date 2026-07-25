"""matches_lite_from_maps rewrite + cached_matches_lite (LOG entry 39).

The rewrite must be a pure speedup: a reference copy of the previous
per-group implementation lives in this test and the new single-pass
version must produce byte-identical output on a store with the awkward
cases (multiple matches, interleaved rows, extra_maps). The cache must
rebuild exactly when the store file's identity changes and never
otherwise.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vpredict import config
from vpredict.data import store as st
from vpredict.data.schema import MapResult, Match
from vpredict.features.asof import add_est_end
from vpredict.modeling.baselines import (cached_matches_lite,
                                         matches_lite_from_maps)


def _reference_impl(maps_df, extra_maps=None):
    """The pre-0038 per-group implementation, kept verbatim as the
    equivalence oracle."""
    df = add_est_end(maps_df)
    extra_maps = extra_maps or {}
    lites = []
    for mid, g in df.groupby("match_id", sort=False):
        g1 = g[g["is_team1"]].sort_values("map_index")
        if g1.empty:
            continue
        r0 = g1.iloc[0]
        lites.append({
            "match_id": mid,
            "start_ts": r0["start_ts"],
            "est_end_ts": r0["est_end_ts"],
            "a": r0["team"], "b": r0["opp"],
            "a_name": r0["team_name"], "b_name": r0["opp_name"],
            "best_of": int(r0["best_of"]),
            "event": r0.get("event", ""), "series": r0.get("series", ""),
            "synthetic": bool(r0.get("synthetic", False)),
            "maps": [(row.map_name, int(row.won), int(row.map_index))
                     for row in g1.itertuples()],
            "maps_extra": list(extra_maps.get(mid, [])),
        })
    lites.sort(key=lambda d: (d["start_ts"], d["match_id"]))
    return lites


def _store_file(tmp_path, n=6):
    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    def _map(mid, name, idx, t1, t2):
        return MapResult(game_id=f"{mid}-{idx}", map_name=name, index=idx,
                         team1_score=t1, team2_score=t2)
    teams = [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]
    matches = []
    for i in range(n):
        (t1, n1), (t2, n2) = teams[i % 3], teams[(i + 1) % 3]
        won = i % 2 == 0
        s1, s2 = (13, 7) if won else (7, 13)
        mid = f"m{i}"
        matches.append(Match(
            match_id=mid, start_ts=t0 + timedelta(hours=6 * i),
            status="completed", best_of=3, event=f"Cup {i % 2}",
            series="Playoffs: Final" if i == n - 1 else "Group A",
            team1_id=t1, team1_name=n1, team2_id=t2, team2_name=n2,
            winner="team1" if won else "team2",
            team1_maps=2 if won else 1, team2_maps=1 if won else 2,
            maps=[_map(mid, "Ascent", 1, s1, s2),
                  _map(mid, "Bind", 2, 13, 9),
                  _map(mid, "Haven", 3, s1, s2)]))
    path = tmp_path / "matches.jsonl"
    st.upsert_matches(matches, path)
    return path


def test_single_pass_matches_reference_exactly(tmp_path):
    path = _store_file(tmp_path)
    maps_df = st.maps_frame(st.iter_matches(path))
    extra = {"m1": ["Split", "Ascent"]}          # dedup case included
    assert matches_lite_from_maps(maps_df, extra) == \
        _reference_impl(maps_df, extra)
    assert matches_lite_from_maps(maps_df) == _reference_impl(maps_df)


def test_cache_hits_on_same_identity_and_rebuilds_on_change(
        tmp_path, monkeypatch):
    path = _store_file(tmp_path, n=4)
    calls = {"n": 0}
    real = st.maps_frame

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr("vpredict.data.store.maps_frame", counting)

    first = cached_matches_lite(path)
    second = cached_matches_lite(path)
    assert second is first                       # same object, no rebuild
    assert calls["n"] == 1

    # top-up: append one more match -> mtime/size move -> rebuild
    extra = Match(
        match_id="m99", start_ts=datetime(2026, 6, 9, tzinfo=timezone.utc),
        status="completed", best_of=1, team1_id="a", team1_name="Alpha",
        team2_id="b", team2_name="Beta", winner="team1",
        team1_maps=1, team2_maps=0,
        maps=[MapResult(game_id="m99-1", map_name="Pearl", index=1,
                        team1_score=13, team2_score=4)])
    st.upsert_matches([extra], path)
    third = cached_matches_lite(path)
    assert calls["n"] == 2
    assert len(third) == len(first) + 1


def test_cache_missing_store_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        cached_matches_lite(tmp_path / "nope.jsonl")
