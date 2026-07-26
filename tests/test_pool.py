"""Pool membership under recency weighting (ASSUMPTIONS §36).

The scenario in the first test is the June 2026 rotation in miniature: a
rotated-out map with a big pile of stale plays versus a brand-new map with a
few very recent ones. Raw counts pick the stale map; the half-life picks the
live one. The remaining tests pin the semantics the docstring promises."""
import pandas as pd
import pytest

from vpredict.modeling.predict import current_pool, pool_table

NOW = pd.Timestamp("2026-07-26T00:00:00Z")


def _plays(entries):
    """entries: (map_name, age_days, n_plays). Emits both team rows per play
    (is_team1 True/False) exactly like store.maps_frame, all Bo1 so the
    estimated end is start + 1.5 h. A 6-hour intra-day offset keeps age-0
    plays finished before NOW."""
    rows = []
    for map_name, age_days, n in entries:
        start = NOW - pd.Timedelta(days=age_days, hours=6)
        for _ in range(n):
            for team1 in (True, False):
                rows.append({"map_name": map_name, "start_ts": start,
                             "best_of": 1, "is_team1": team1})
    return pd.DataFrame(rows)


def test_recent_light_map_outweighs_stale_heavy_map():
    df = _plays([("Stalemap", 50, 30), ("Newmap", 2, 8)])
    # Raw counts (weighting disabled) look at bulk and pick the rotated-out map:
    assert current_pool(df, NOW, size=1, half_life_days=None) == ["Stalemap"]
    # 14-day half-life: 30 * 0.5**(50/14) ~= 2.5 vs 8 * 0.5**(2/14) ~= 7.2.
    assert current_pool(df, NOW, size=1, half_life_days=14.0) == ["Newmap"]
    # Both still belong to a size-2 pool; only the ORDER flips.
    assert current_pool(df, NOW, size=2, half_life_days=14.0) == [
        "Newmap", "Stalemap"]


def test_half_life_means_half_every_half_life():
    # Two single plays 14 days apart: the older must weigh exactly half.
    tbl = pool_table(_plays([("A", 2, 1), ("B", 16, 1)]), NOW,
                     half_life_days=14.0)
    assert tbl.loc["B", "weighted"] == pytest.approx(
        0.5 * tbl.loc["A", "weighted"], rel=1e-9)


def test_window_is_a_hard_support_bound():
    # 40 plays just past the window contribute nothing, not even decayed.
    df = _plays([("Ancient", 61, 40), ("Fresh", 1, 1)])
    tbl = pool_table(df, NOW, window_days=60)
    assert "Ancient" not in tbl.index
    assert current_pool(df, NOW, window_days=60) == ["Fresh"]


def test_empty_window_falls_back_to_all_finished_history():
    df = _plays([("Oldie", 90, 3)])
    assert current_pool(df, NOW, window_days=60) == ["Oldie"]


def test_equal_weights_break_ties_alphabetically():
    df = _plays([("Breeze", 5, 1), ("Ascent", 5, 1)])
    assert current_pool(df, NOW) == ["Ascent", "Breeze"]


def test_mirror_team_rows_are_not_double_counted():
    tbl = pool_table(_plays([("Lotus", 3, 4)]), NOW)
    assert int(tbl.loc["Lotus", "plays"]) == 4


def test_future_and_in_progress_plays_are_excluded():
    df = _plays([("Done", 1, 1)])
    live = pd.DataFrame([
        {"map_name": "Tomorrow", "start_ts": NOW + pd.Timedelta(days=1),
         "best_of": 1, "is_team1": True},
        # started 30 min ago -> estimated end is still in the future
        {"map_name": "InProgress", "start_ts": NOW - pd.Timedelta(minutes=30),
         "best_of": 1, "is_team1": True},
    ])
    tbl = pool_table(pd.concat([df, live], ignore_index=True), NOW)
    assert list(tbl.index) == ["Done"]
