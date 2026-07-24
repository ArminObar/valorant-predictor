#!/usr/bin/env python3
"""Measure the walk-forward backtest's compute cost — WITHOUT building it.

    python scripts/backtest_cost.py \
        --features-cache data/processed/features_cache.parquet

Prints, from measurements on THIS machine:
  1. one-time feature-matrix build cost (or the cache-load cost if cached);
  2. the number of retrain points a walk-forward replay of the PRODUCTION
     cadence produces over the store's real timeline (6 h ticks; retrain when
     the bundle is >= RETRAIN_MAX_AGE_DAYS old or >= RETRAIN_NEW_MATCHES new
     completed matches arrived — the same rule as serving/refresh.py);
  3. the measured wall time of ONE production-shaped retrain unit
     (select_model = LR + gated LightGBM + calibration) on a mid-timeline
     training prefix, run twice;
  4. the arithmetic: production-cadence total, and the retrain-before-every-
     match alternative for comparison.

Why the feature matrix is built ONCE and reused across every simulated
retrain: each row's features are as-of that row's own match start by
construction (the leakage rule), so they do not depend on when the model
was trained — a retrain at simulated time T simply trains on the rows whose
estimated finish precedes T. Rebuilding features per retrain would multiply
cost by ~100 for identical numbers.
"""
from __future__ import annotations

import argparse
import os
import platform
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from vpredict import config
from vpredict.features.build import FeatureSet, augment_swapped, build_features
from vpredict.modeling.train import select_model


def simulate_cadence(match_starts: pd.Series, warmup_matches: int,
                     tick_hours: int = 6) -> dict:
    """Replay the production retrain rule over the store's real timeline.
    `match_starts` = one start_ts per usable match, sorted ascending."""
    starts = match_starts.sort_values().reset_index(drop=True)
    t = starts.iloc[warmup_matches - 1] if len(starts) >= warmup_matches \
        else starts.iloc[-1]
    end = starts.iloc[-1]
    completed_at = lambda ts: int(starts.searchsorted(ts, side="right"))
    last_train_t, last_train_n = t, completed_at(t)
    n_retrains = 1                                   # the warmup train
    tick = timedelta(hours=tick_hours)
    while t < end:
        t = t + tick
        n_now = completed_at(t)
        aged = (t - last_train_t) >= timedelta(days=config.RETRAIN_MAX_AGE_DAYS)
        grew = (n_now - last_train_n) >= config.RETRAIN_NEW_MATCHES
        if aged or grew:
            n_retrains += 1
            last_train_t, last_train_n = t, n_now
    return {"n_retrains": n_retrains,
            "window_days": (end - starts.iloc[warmup_matches - 1]).days,
            "n_matches_after_warmup": len(starts) - warmup_matches}


def time_one_retrain(fs: FeatureSet) -> list[float]:
    """One production-shaped retrain at the 70% timeline point, mirroring
    train_and_save exactly: rolling-origin family scores over train+val with
    hysteresis, then the final fit + calibration of the chosen family.
    Returned twice-measured (cache warmth)."""
    from vpredict.modeling.train import choose_family, rolling_origin_scores

    order = (fs.meta[["match_id", "start_ts"]].drop_duplicates("match_id")
             .sort_values(["start_ts", "match_id"]))
    mids = order["match_id"].to_list()
    n = len(mids)
    tr_ids = set(mids[: int(n * 0.70)])
    va_ids = set(mids[int(n * 0.70): int(n * 0.85)])
    tr = fs.meta["match_id"].isin(tr_ids).to_numpy()
    va = fs.meta["match_id"].isin(va_ids).to_numpy()
    sel_mask = tr | va
    times = []
    for _ in range(2):
        t0 = time.perf_counter()
        scores = rolling_origin_scores(
            fs.X[sel_mask].reset_index(drop=True),
            fs.y[sel_mask].reset_index(drop=True),
            n_train_matches=len(tr_ids), augment=augment_swapped)
        decision = choose_family(scores, incumbent_family="lightgbm")
        X_tr, y_tr = augment_swapped(fs.X[tr], fs.y[tr])
        select_model(X_tr, y_tr, fs.X[va], fs.y[va],
                     n_train_matches=len(tr_ids),
                     families=[decision["chosen"]])
        times.append(time.perf_counter() - t0)
    return times


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--features-cache", default=None,
                    help="joblib FeatureSet path: load if present, else build "
                         "from the store (timed) and save here")
    ap.add_argument("--warmup-matches", type=int, default=300,
                    help="usable matches before the first simulated retrain")
    args = ap.parse_args()

    print(f"machine: {platform.machine()} | cpus: {os.cpu_count()} | "
          f"python {platform.python_version()}")

    cache = Path(args.features_cache) if args.features_cache else None
    t0 = time.perf_counter()
    if cache and cache.exists():
        fs = FeatureSet.load(cache)
        t_build = time.perf_counter() - t0
        build_kind = f"cache load ({cache})"
        print(f"[1] feature matrix: {t_build:.1f}s ({build_kind}); a cold "
              f"build costs what scripts/train.py minus modeling costs — "
              f"measure with no cache present if needed")
    else:
        fs = build_features()
        t_build = time.perf_counter() - t0
        build_kind = "cold build from store"
        if cache:
            fs.save(cache)
        print(f"[1] feature matrix: {t_build:.1f}s ({build_kind})")

    starts = (fs.meta[["match_id", "start_ts"]].drop_duplicates("match_id")
              ["start_ts"])
    sim = simulate_cadence(starts, args.warmup_matches)
    print(f"[2] production cadence replay ({config.RETRAIN_MAX_AGE_DAYS}d / "
          f"{config.RETRAIN_NEW_MATCHES} new, 6h ticks, warmup "
          f"{args.warmup_matches}): {sim['n_retrains']} retrains over "
          f"{sim['window_days']} days; {sim['n_matches_after_warmup']} "
          f"matches predicted after warmup")

    t1, t2 = time_one_retrain(fs)
    t_fit = min(t1, t2)
    print(f"[3] one retrain unit (select LR + gated LightGBM + calibrate) on "
          f"the 70% prefix: {t1:.1f}s first, {t2:.1f}s second; using "
          f"{t_fit:.1f}s")

    prod = t_build + sim["n_retrains"] * t_fit
    full = t_build + sim["n_matches_after_warmup"] * t_fit
    print(f"[4] totals on THIS machine — production cadence: "
          f"~{prod / 60:.0f} min ({sim['n_retrains']} x {t_fit:.1f}s + "
          f"build); retrain-before-every-match: ~{full / 3600:.1f} h "
          f"({sim['n_matches_after_warmup']} x {t_fit:.1f}s + build)")
    print("prediction passes are vectorized per segment and cost seconds "
          "total; per-retrain prefixes smaller than the 70% point fit "
          "faster, so [4] is an upper bound at fixed hardware")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
