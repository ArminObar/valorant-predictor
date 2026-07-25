"""predict_one payload contract — the per-map surface.

Field finding (LOG entry 37): live per-map probabilities displayed one
identical value across the whole pool. Investigation showed the wiring was
correct — a step-function calibrator legitimately tied the maps — which
also means "per-map probabilities are distinct" is NOT a valid invariant
and cannot be asserted. What CAN be pinned:

1. the payload exposes `per_map_elo`, the model's map-specific Elo input,
   computed from the same feature-K snapshot the feature row uses;
2. those leans actually vary across maps when the underlying history says
   they should (so the UI always has real per-map signal to show, however
   the calibrator quantizes the probabilities);
3. `per_map` and `per_map_elo` cover exactly the requested pool.

Synthetic history mirrors tests/test_leakage.py's builder (trimmed): two
teams whose results DIFFER BY MAP — red dominates Ascent, blu dominates
Bind, Haven splits — so the per-map Elo blend must separate the maps.
"""
from __future__ import annotations

import pandas as pd

from vpredict import config
from vpredict.data.schema import Match
from vpredict.features.asof import AsOfEngine
from vpredict.features.build import augment_swapped, build_features
from vpredict.modeling.baselines import elo_snapshot_at, matches_lite_from_maps
from vpredict.modeling.predict import predict_one
from vpredict.modeling.train import PlattCalibrator, fit_lr

BASE = pd.Timestamp("2025-01-06 12:00", tz="UTC")
DUR3 = pd.Timedelta(hours=config.ASSUMED_DURATION_HOURS[3])
LINEUPS = {"red": tuple(f"r{i}" for i in range(5)),
           "blu": tuple(f"b{i}" for i in range(5))}


def _map_rows(mid, start, a, b, map_name, map_index, a_score, b_score):
    def halves(score):
        return score // 2, score - score // 2
    a_atk, a_def = halves(a_score)
    b_atk, b_def = halves(b_score)
    a_pist = 2 if a_score > b_score else 0
    common = dict(match_id=mid, start_ts=start, best_of=3,
                  event="Synthetic Cup", series="Group Stage",
                  map_name=map_name, map_index=map_index, synthetic=True)
    row_a = dict(common, team=a, team_name=a.upper(), opp=b,
                 opp_name=b.upper(), is_team1=True,
                 won=int(a_score > b_score), rounds_won=a_score,
                 rounds_lost=b_score, atk_rw=a_atk, atk_rl=b_def,
                 def_rw=a_def, def_rl=b_atk, fk=a_score, fd=b_score,
                 pistols_won=a_pist, pistols_played=2, lineup=LINEUPS[a],
                 multikills=3, clutch_wins=1, fullbuy_n=10,
                 fullbuy_w=min(a_score, 10), lowbuy_n=6,
                 lowbuy_w=max(0, a_score - 9))
    row_b = dict(common, team=b, team_name=b.upper(), opp=a,
                 opp_name=a.upper(), is_team1=False,
                 won=int(b_score > a_score), rounds_won=b_score,
                 rounds_lost=a_score, atk_rw=b_atk, atk_rl=a_def,
                 def_rw=b_def, def_rl=a_atk, fk=b_score, fd=a_score,
                 pistols_won=2 - a_pist, pistols_played=2, lineup=LINEUPS[b],
                 multikills=3, clutch_wins=1, fullbuy_n=10,
                 fullbuy_w=min(b_score, 10), lowbuy_n=6,
                 lowbuy_w=max(0, b_score - 9))
    return [row_a, row_b]


def _history() -> pd.DataFrame:
    rows: list[dict] = []
    for i in range(8):
        start = BASE + pd.Timedelta(days=2 * i)
        mid = f"m{i}"
        # Map-dependent outcomes: red crushes Ascent, blu crushes Bind,
        # Haven alternates. Per-map Elo MUST end up map-dependent.
        rows += _map_rows(mid, start, "red", "blu", "Ascent", 1, 13, 5)
        rows += _map_rows(mid, start, "red", "blu", "Bind", 2, 5, 13)
        haven = (13, 8) if i % 2 == 0 else (8, 13)
        rows += _map_rows(mid, start, "red", "blu", "Haven", 3, *haven)
    return pd.DataFrame(rows)


def test_per_map_payload_contract():
    maps_df = _history()
    fs = build_features(maps_df, min_history=1, spot_checks=2)
    X_tr, y_tr = augment_swapped(fs.X, fs.y)
    lr = fit_lr(X_tr, y_tr, fs.X, fs.y.to_numpy())
    cal = PlattCalibrator().fit(
        lr["model"].predict_proba(fs.X)[:, 1], fs.y.to_numpy())
    bundle = {"model": lr["model"], "calibrator": cal,
              "feature_names": fs.feature_names,
              "params": {"half_life_days": config.DEFAULT_HALF_LIFE_DAYS,
                         "roster_factor": config.DEFAULT_ROSTER_FACTOR,
                         "elo_k_features": config.DEFAULT_ELO_K},
              "version": "contract-test"}

    now_ts = BASE + pd.Timedelta(days=30)
    engine = AsOfEngine(maps_df,
                        half_life_days=config.DEFAULT_HALF_LIFE_DAYS,
                        roster_factor=config.DEFAULT_ROSTER_FACTOR)
    lites = matches_lite_from_maps(maps_df)
    pool = ["Ascent", "Bind", "Haven"]
    um = Match(match_id="u1", start_ts=(now_ts + DUR3).to_pydatetime(),
               status="upcoming", best_of=3, event="Synthetic Cup",
               series="Playoffs: Grand Final", team1_id="red",
               team1_name="RED", team2_id="blu", team2_name="BLU")

    p = predict_one(bundle, engine, lites, pool, um, now_ts)

    # Coverage: both per-map dicts speak for exactly the requested pool.
    assert set(p["per_map"]) == set(pool)
    assert set(p["per_map_elo"]) == set(pool)

    # The leans are the SAME numbers the feature row consumed: recompute
    # from the identical snapshot and compare.
    probe = {"a": "red", "b": "blu", "maps": [], "maps_extra": pool}
    snap = elo_snapshot_at(lites, now_ts, probe, k=config.DEFAULT_ELO_K)
    for m in pool:
        ra, rb = snap["maps"][m]
        assert p["per_map_elo"][m] == round(float(ra - rb), 1)

    # Real per-map variation: map-dependent history must separate the
    # leans (red's Ascent edge positive, Bind edge negative, and not one
    # flat number across the pool).
    assert p["per_map_elo"]["Ascent"] > 0 > p["per_map_elo"]["Bind"]
    assert len({round(v) for v in p["per_map_elo"].values()}) >= 2

    # Probabilities may legitimately TIE (step calibrator) — assert only
    # validity, never distinctness.
    for v in p["per_map"].values():
        assert 0.0 < v < 1.0
