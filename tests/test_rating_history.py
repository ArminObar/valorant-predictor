"""elo_trajectory — the match-page chart's data must be the SAME rating
state everything else uses, not a lookalike.

Pinned: (1) consistency — a trajectory's final value equals the overall
rating `elo_snapshot_at` reports at the identical cutoff, because both
replay under the identical eligibility rule and order; (2) the cutoff
excludes matches whose estimated finish is after it; (3) last-n
truncation with chronological points; (4) the API attaches the block for
a real store and survives an absent bundle (default-K fallback).
"""
from __future__ import annotations

import pandas as pd

from vpredict import config
from vpredict.modeling.baselines import elo_snapshot_at, elo_trajectory

T0 = pd.Timestamp("2025-01-06 12:00", tz="UTC")
H = pd.Timedelta(hours=1)


def _lite(mid, start, a, b, a_wins, b_wins):
    maps = ([("Ascent", 1, 1)] * a_wins) + ([("Bind", 0, 2)] * b_wins)
    return {"match_id": mid, "start_ts": start, "est_end_ts": start + 3 * H,
            "a": a, "b": b, "a_name": a.upper(), "b_name": b.upper(),
            "maps": maps, "maps_extra": []}


def _lites():
    return [
        _lite("m1", T0, "red", "blu", 2, 0),
        _lite("m2", T0 + 24 * H, "red", "grn", 2, 1),
        _lite("m3", T0 + 48 * H, "blu", "grn", 0, 2),
        _lite("m4", T0 + 72 * H, "red", "blu", 1, 2),
    ]


def test_trajectory_final_rating_matches_snapshot():
    cutoff = T0 + 100 * H
    traj = elo_trajectory(_lites(), cutoff, {"red", "blu"}, n=10)
    probe = {"a": "red", "b": "blu", "maps": [], "maps_extra": []}
    snap = elo_snapshot_at(_lites(), cutoff, probe, k=config.DEFAULT_ELO_K)
    assert traj["red"][-1]["rating"] == round(snap["elo_a"], 1)
    assert traj["blu"][-1]["rating"] == round(snap["elo_b"], 1)


def test_cutoff_excludes_unfinished_matches():
    cutoff = T0 + 73 * H                    # m4 started, est end T0+75H
    traj = elo_trajectory(_lites(), cutoff, {"red"}, n=10)
    assert len(traj["red"]) == 2            # m1, m2 only
    assert all(pd.Timestamp(p["ts"]) <= cutoff for p in traj["red"])


def test_last_n_truncation_and_order():
    cutoff = T0 + 100 * H
    traj = elo_trajectory(_lites(), cutoff, {"red"}, n=2)
    pts = traj["red"]
    assert len(pts) == 2                    # m2, m4 (last two)
    assert pd.Timestamp(pts[0]["ts"]) < pd.Timestamp(pts[1]["ts"])
    assert pts[0]["rating"] != pts[1]["rating"]
    assert {p["won"] for p in pts} == {True, False}


def test_match_detail_attaches_rating_history(tmp_path, monkeypatch):
    """Real endpoint, tiny real store, no bundle on disk: the chart block
    appears with default-K ratings and per-team points."""
    from datetime import datetime, timedelta, timezone
    from fastapi.testclient import TestClient
    from vpredict.data.schema import Match, MapResult
    from vpredict.data import store as st
    from vpredict.serving.api import create_app
    from vpredict.serving.ledger import Ledger

    data = tmp_path / "data"
    (data / "raw").mkdir(parents=True)
    monkeypatch.setattr(config, "MATCHES_JSONL", data / "raw" / "matches.jsonl")
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    def _map(mid, name, idx, t1, t2):
        return MapResult(game_id=f"{mid}-{idx}", map_name=name, index=idx,
                         team1_score=t1, team2_score=t2)
    hist = []
    for i in range(3):
        won = i != 1
        s1, s2 = (13, 7) if won else (7, 13)
        mid = f"h{i}"
        hist.append(Match(
            match_id=mid, start_ts=t0 + timedelta(days=i),
            status="completed", best_of=3, team1_id="a", team1_name="Alpha",
            team2_id="b", team2_name="Beta",
            winner="team1" if won else "team2",
            team1_maps=2 if won else 1, team2_maps=1 if won else 2,
            maps=[_map(mid, "Ascent", 1, s1, s2),
                  _map(mid, "Bind", 2, 13, 9),
                  _map(mid, "Haven", 3, s1, s2)]))
    st.upsert_matches(hist, config.MATCHES_JSONL)
    led = Ledger(data / "serving" / "ledger.sqlite")
    start = datetime.now(timezone.utc) + timedelta(hours=3)
    led.insert_prediction(match_id="m9", start_ts=start, team1="a",
                          team2="b", team1_name="Alpha", team2_name="Beta",
                          event="Cup", best_of=3, p_model=0.61, p_elo=0.55,
                          model_version="t", low_history=False)
    led.close()

    c = TestClient(create_app(data_dir=data))
    out = c.get("/api/match/m9").json()
    rh = out.get("rating_history")
    assert rh, "rating_history missing"
    assert rh["k"] == float(config.DEFAULT_ELO_K)       # no bundle: fallback
    assert set(rh["teams"]) == {"a", "b"}
    a_pts = rh["teams"]["a"]["points"]
    assert 1 <= len(a_pts) <= config.RATING_TRAJECTORY_N
    assert a_pts[-1]["rating"] != config.ELO_BASE       # ratings moved
    assert rh["teams"]["a"]["name"] == "Alpha"
