"""Temporal-leakage tests — the non-negotiable from the build spec.

Strategy: build a small internally consistent synthetic history, take feature
snapshots at a cutoff, then POISON THE FUTURE with absurd results and assert
bit-for-bit identical features. A boundary case (a match finishing just BEFORE
the cutoff) must change the features, proving the test can actually fail.

Covered surfaces: AsOfEngine snapshots, the as-of league priors used for
shrinkage, the event-queue EloBook (including the overlapping-match case), and
the full `build_features` matrix.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from vpredict import config
from vpredict.features.asof import AsOfEngine, add_est_end
from vpredict.features.build import build_features
from vpredict.modeling.baselines import compute_prematch_elo, matches_lite_from_maps

BASE = pd.Timestamp("2025-01-06 12:00", tz="UTC")
DUR3 = pd.Timedelta(hours=config.ASSUMED_DURATION_HOURS[3])
LINEUPS = {
    "red": tuple(f"r{i}" for i in range(5)),
    "blu": tuple(f"b{i}" for i in range(5)),
    "grn": tuple(f"g{i}" for i in range(5)),
}


def _map_rows(mid: str, start: pd.Timestamp, a: str, b: str, map_name: str,
              map_index: int, a_score: int, b_score: int, *, best_of: int = 3,
              series: str = "Group Stage") -> list[dict]:
    """Two mirrored team rows for one map, with internally consistent splits."""
    def halves(score: int) -> tuple[int, int]:
        return score // 2, score - score // 2          # (atk_rw, def_rw)

    a_atk, a_def = halves(a_score)
    b_atk, b_def = halves(b_score)
    a_pist = 2 if a_score > b_score else 0
    common = dict(match_id=mid, start_ts=start, best_of=best_of,
                  event="Synthetic Cup", series=series, map_name=map_name,
                  map_index=map_index, synthetic=True)
    row_a = dict(common, team=a, team_name=a.upper(), opp=b, opp_name=b.upper(),
                 is_team1=True, won=int(a_score > b_score),
                 rounds_won=a_score, rounds_lost=b_score,
                 atk_rw=a_atk, atk_rl=b_def, def_rw=a_def, def_rl=b_atk,
                 fk=a_score, fd=b_score, pistols_won=a_pist, pistols_played=2,
                 lineup=LINEUPS[a], multikills=3, clutch_wins=1,
                 fullbuy_n=10, fullbuy_w=min(a_score, 10),
                 lowbuy_n=6, lowbuy_w=max(0, a_score - 9))
    row_b = dict(common, team=b, team_name=b.upper(), opp=a, opp_name=a.upper(),
                 is_team1=False, won=int(b_score > a_score),
                 rounds_won=b_score, rounds_lost=a_score,
                 atk_rw=b_atk, atk_rl=a_def, def_rw=b_def, def_rl=a_atk,
                 fk=b_score, fd=a_score, pistols_won=2 - a_pist, pistols_played=2,
                 lineup=LINEUPS[b], multikills=3, clutch_wins=1,
                 fullbuy_n=10, fullbuy_w=min(b_score, 10),
                 lowbuy_n=6, lowbuy_w=max(0, b_score - 9))
    return [row_a, row_b]


def _bo3(mid: str, start: pd.Timestamp, a: str, b: str,
         scores: list[tuple[int, int]], maps=("Ascent", "Bind", "Haven"),
         series: str = "Group Stage") -> list[dict]:
    rows: list[dict] = []
    for i, (sa, sb) in enumerate(scores):
        rows += _map_rows(mid, start, a, b, maps[i], i + 1, sa, sb, series=series)
    return rows


def _history() -> pd.DataFrame:
    """12 non-overlapping matches over 12 weeks among three teams."""
    rows: list[dict] = []
    pairs = [("red", "blu"), ("blu", "grn"), ("red", "grn")]
    for w in range(12):
        a, b = pairs[w % 3]
        strong_a = a == "red" or (a == "blu" and b == "grn")
        s1 = (13, 7) if strong_a else (7, 13)
        s2 = (13, 10) if strong_a else (10, 13)
        rows += _bo3(f"m{w:03d}", BASE + pd.Timedelta(days=7 * w), a, b, [s1, s2])
    return pd.DataFrame(rows)


def _poison(df: pd.DataFrame, start: pd.Timestamp, mid: str = "poison") -> pd.DataFrame:
    """Absurd future results for every team: red obliterated on both maps."""
    rows = _bo3(mid, start, "red", "blu", [(0, 13), (0, 13)])
    rows += _bo3(mid + "2", start + pd.Timedelta(hours=6), "grn", "red", [(13, 0), (13, 0)])
    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)


def _snap_equal(s1, s2) -> list[str]:
    bad = []
    for f in dataclasses.fields(s1):
        v1, v2 = getattr(s1, f.name), getattr(s2, f.name)
        if f.name == "extras":
            continue
        if v1 is None or v2 is None:
            if v1 is not v2:
                bad.append(f.name)
        elif not math.isclose(float(v1), float(v2), rel_tol=1e-12, abs_tol=1e-12):
            bad.append(f.name)
    return bad


CUTOFF = BASE + pd.Timedelta(days=7 * 12)   # after all 12 matches finished


# --------------------------------------------------------------------------- engine
def test_future_poison_does_not_change_snapshot():
    hist = _history()
    clean = AsOfEngine(hist).team_snapshot("red", CUTOFF)
    # Poison starts AT the cutoff -> estimated end strictly after it.
    poisoned = AsOfEngine(_poison(hist, CUTOFF)).team_snapshot("red", CUTOFF)
    assert _snap_equal(clean, poisoned) == []


def test_eligibility_is_estimated_finish_not_start():
    """A match that STARTS before the cutoff but finishes after must be excluded."""
    hist = _history()
    clean = AsOfEngine(hist).team_snapshot("red", CUTOFF)
    still_running = AsOfEngine(
        _poison(hist, CUTOFF - DUR3 + pd.Timedelta(seconds=1))
    ).team_snapshot("red", CUTOFF)
    assert _snap_equal(clean, still_running) == []


def test_boundary_teeth():
    """Poison that finishes exactly at / just before the cutoff MUST move the
    numbers — otherwise the tests above prove nothing."""
    hist = _history()
    clean = AsOfEngine(hist).team_snapshot("red", CUTOFF)
    finished = AsOfEngine(
        _poison(hist, CUTOFF - DUR3 - pd.Timedelta(hours=7))
    ).team_snapshot("red", CUTOFF)
    changed = _snap_equal(clean, finished)
    assert "round_share" in changed and "pistol_wr" in changed


def test_map_filtered_snapshot_is_leak_free():
    hist = _history()
    clean = AsOfEngine(hist).team_snapshot("red", CUTOFF, map_name="Ascent")
    poisoned = AsOfEngine(_poison(hist, CUTOFF)).team_snapshot("red", CUTOFF, map_name="Ascent")
    assert _snap_equal(clean, poisoned) == []


# --------------------------------------------------------------------------- priors
def test_league_priors_are_as_of():
    hist = _history()
    clean = AsOfEngine(hist).league_priors(CUTOFF)
    poisoned = AsOfEngine(_poison(hist, CUTOFF)).league_priors(CUTOFF)
    for k in clean:
        assert math.isclose(clean[k], poisoned[k], rel_tol=1e-12, abs_tol=1e-12), k
    # ...and they must respond to the past (teeth).
    past = AsOfEngine(_poison(hist, CUTOFF - DUR3 - pd.Timedelta(days=1))).league_priors(CUTOFF)
    assert not math.isclose(clean["atk_eff"], past["atk_eff"], rel_tol=1e-12)


# --------------------------------------------------------------------------- Elo
def test_elo_event_queue_overlap_and_future():
    hist = _history()
    t_overlap = BASE + pd.Timedelta(days=90)
    overlap = _bo3("ov1", t_overlap, "red", "blu", [(13, 0), (13, 0)])
    # Second match starts 1h after ov1 starts — ov1 has NOT finished yet.
    overlap += _bo3("ov2", t_overlap + pd.Timedelta(hours=1), "red", "grn", [(13, 5), (13, 5)])
    df = pd.concat([hist, pd.DataFrame(overlap)], ignore_index=True)
    table = compute_prematch_elo(matches_lite_from_maps(df))
    # ov1 had not finished when ov2 started: red's rating at ov2 must equal
    # red's rating at ov1 (identical pre-state), despite ov1's 2-0 stomp.
    assert math.isclose(table["ov2"]["elo_a"], table["ov1"]["elo_a"], rel_tol=1e-12)
    # Teeth: if ov2 instead starts AFTER ov1's estimated finish, it must differ.
    later = _bo3("ov3", t_overlap + DUR3 + pd.Timedelta(minutes=5),
                 "red", "grn", [(13, 5), (13, 5)])
    df_later = pd.concat([hist, pd.DataFrame(_bo3("ov1", t_overlap, "red", "blu",
                                                  [(13, 0), (13, 0)])),
                          pd.DataFrame(later)], ignore_index=True)
    table_later = compute_prematch_elo(matches_lite_from_maps(df_later))
    assert not math.isclose(table_later["ov3"]["elo_a"], table["ov1"]["elo_a"], rel_tol=1e-9)
    # Future poison never changes historical snapshots.
    poisoned = compute_prematch_elo(matches_lite_from_maps(_poison(df, CUTOFF + pd.Timedelta(days=30))))
    for mid in table:
        assert math.isclose(table[mid]["p_a"], poisoned[mid]["p_a"], rel_tol=1e-12), mid


def test_elo_no_within_match_leak():
    """Both maps of a match must see the SAME pre-match ratings (map 1's result
    must not update ratings before map 2 of the same match)."""
    hist = _history()
    lites = matches_lite_from_maps(hist)
    table = compute_prematch_elo(lites)
    # Recompute with map 2 results flipped in the LAST match: earlier snapshots
    # identical, and the last match's own snapshot identical too.
    df2 = hist.copy()
    last = df2["match_id"] == "m011"
    df2.loc[last & (df2["map_index"] == 2), "won"] = 1 - df2.loc[
        last & (df2["map_index"] == 2), "won"]
    table2 = compute_prematch_elo(matches_lite_from_maps(df2))
    for mid in table:
        assert math.isclose(table[mid]["elo_a"], table2[mid]["elo_a"], rel_tol=1e-12), mid


# --------------------------------------------------------------------------- full build
def test_build_features_unchanged_by_future_poison():
    hist = _history()
    fs1 = build_features(hist, spot_checks=4)
    fs2 = build_features(_poison(hist, CUTOFF), spot_checks=4)
    assert fs1.feature_names == fs2.feature_names
    key = ["match_id", "map_index"]
    common = set(map(tuple, fs1.meta[key].to_numpy())) & set(map(tuple, fs2.meta[key].to_numpy()))
    assert len(common) >= 6
    i1 = fs1.meta.set_index(key).index
    i2 = fs2.meta.set_index(key).index
    m1 = [i for i, k in enumerate(i1) if k in common]
    m2 = [i for i, k in enumerate(i2) if k in common]
    a = fs1.X.iloc[m1].reset_index(drop=True)
    b = fs2.X.iloc[m2].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-12, atol=1e-12)
    assert (fs1.y.iloc[m1].to_numpy() == fs2.y.iloc[m2].to_numpy()).all()


def test_build_spot_check_has_teeth(monkeypatch):
    """If the engine WERE leaky, the build-time spot-check must blow up."""
    from vpredict.features import build as build_mod

    real = build_mod._recompute_row

    def corrupted(maps_df, fs, i):
        row = real(maps_df, fs, i)
        row.iloc[0] += 0.123   # simulate a leaked/incorrect recomputation
        return row

    monkeypatch.setattr(build_mod, "_recompute_row", corrupted)
    with pytest.raises(RuntimeError, match="LEAKAGE SPOT-CHECK FAILED"):
        build_features(_history(), spot_checks=2)


def test_est_end_matches_config():
    df = add_est_end(_history())
    got = (df["est_end_ts"] - df["start_ts"]).dt.total_seconds().unique() / 3600
    assert set(np.round(got, 6)) == {config.ASSUMED_DURATION_HOURS[3]}
