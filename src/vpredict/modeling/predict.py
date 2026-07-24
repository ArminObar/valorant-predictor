"""Predict upcoming matches with the trained bundle.

Pre-veto series probability: per-map calibrated probabilities are computed for
every map in the CURRENT pool (top-N maps by play frequency over the last
CURRENT_POOL_WINDOW_DAYS), averaged with uniform pool weights (documented
simplification — real pick/ban tendencies are future work), and pushed through
the exact best-of DP. The as-of cutoff is NOW: only matches whose estimated
finish precedes this moment contribute — the same leakage rule as training.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone

import pandas as pd

from .. import config
from ..data import store
from ..data.schema import Match
from ..features.asof import AsOfEngine, snapshot_diffs, add_est_end
from ..features.build import _assemble_row
from ..modeling import series as sr
from ..modeling.baselines import elo_snapshot_at, matches_lite_from_maps
from ..modeling.train import predict_calibrated

log = logging.getLogger("vpredict.predict")


def current_pool(maps_df: pd.DataFrame, now: pd.Timestamp,
                 window_days: int = config.CURRENT_POOL_WINDOW_DAYS,
                 size: int = config.CURRENT_POOL_SIZE) -> list[str]:
    df = add_est_end(maps_df)
    recent = df[(df["est_end_ts"] <= now) &
                (df["start_ts"] >= now - pd.Timedelta(days=window_days))]
    if recent.empty:
        recent = df[df["est_end_ts"] <= now]
    counts = recent[recent["is_team1"]]["map_name"].value_counts()
    return counts.head(size).index.tolist()


def _elo_p(pair) -> float:
    ra, rb = pair
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / config.ELO_SCALE))


def predict_upcoming(bundle: dict, history, upcoming: list[Match],
                     now: datetime | None = None) -> list[dict]:
    # `history` may be any iterable of Match (the refresh cycle passes
    # store.iter_matches); it is consumed exactly once, by maps_frame.
    now_ts = pd.Timestamp(now or datetime.now(timezone.utc))
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    maps_df = store.maps_frame(history)
    if maps_df.empty:
        raise ValueError("no completed history — scrape before predicting")
    params = bundle["params"]
    engine = AsOfEngine(maps_df,
                        half_life_days=params["half_life_days"],
                        roster_factor=params["roster_factor"])
    lites = matches_lite_from_maps(maps_df)
    pool = current_pool(maps_df, now_ts)
    feature_names = bundle["feature_names"]
    dummy_cols = [c for c in feature_names
                  if c.startswith("map_") and c != "map_elo_diff"]

    out: list[dict] = []
    for um in upcoming:
        a, b = um.key_team("team1"), um.key_team("team2")
        snap_a = engine.team_snapshot(a, now_ts)
        snap_b = engine.team_snapshot(b, now_ts)
        low_history = min(snap_a.n_maps, snap_b.n_maps) < config.MIN_MAPS_HISTORY
        diffs = snapshot_diffs(snap_a, snap_b)
        probe = {"a": a, "b": b, "maps": [], "maps_extra": pool}
        e_feat = elo_snapshot_at(lites, now_ts, probe,
                                 k=params.get("elo_k_features", config.DEFAULT_ELO_K))
        e_base = elo_snapshot_at(lites, now_ts, probe,
                                 k=bundle.get("elo_k_baseline", config.DEFAULT_ELO_K))
        playoff = float(store.is_playoff(um.series))
        hist_min = math.log1p(min(snap_a.n_maps, snap_b.n_maps))

        rows, kept_maps = [], []
        for name in pool:
            # Same assembler the training pipeline uses -> keys cannot drift.
            row = _assemble_row(diffs, e_feat, name, um.best_of,
                                bool(playoff), hist_min)
            for k in list(row):
                if row[k] is None:
                    row[k] = 0.0
            for c in dummy_cols:
                row[c] = 1.0 if c == f"map_{name}" else 0.0
            rows.append(row)
            kept_maps.append(name)
        X = pd.DataFrame(rows)
        missing = [c for c in feature_names
                   if c not in X and not c.startswith("map_")]
        if missing:                       # loud, never a silent zero-fill
            raise RuntimeError(f"predict-time features missing {missing}; "
                               "training and serving feature schemas drifted")
        for c in feature_names:
            if c not in X:                # only map dummies can land here
                X[c] = 0.0
        X = X[feature_names]
        p_maps = predict_calibrated(bundle, X)
        p_map_mean = float(p_maps.mean())
        p_model = sr.series_prob([p_map_mean] * int(um.best_of))
        pe_maps = [_elo_p(e_base["maps"][m]) for m in kept_maps]
        pe_mean = float(sum(pe_maps) / len(pe_maps))
        p_elo = sr.series_prob([pe_mean] * int(um.best_of))

        out.append({
            "match_id": um.match_id,
            "start_ts": um.start_ts.isoformat(),
            "event": um.event, "series": um.series, "best_of": um.best_of,
            "team1": a, "team2": b,
            "team1_name": um.team1_name, "team2_name": um.team2_name,
            "p_model": round(p_model, 4), "p_elo": round(p_elo, 4),
            "per_map": {m: round(float(p), 4) for m, p in zip(kept_maps, p_maps)},
            "pool": pool, "low_history": low_history,
            "model_version": bundle.get("version", "unknown"),
        })
    return out


def run_predictions(bundle: dict, history, upcoming: list[Match],
                    ledger, now: datetime | None = None,
                    json_path=None) -> dict:
    """Predict, write the ledger (freeze rules apply), and publish the JSON the
    API serves. Returns counters."""
    now = now or datetime.now(timezone.utc)
    preds = predict_upcoming(bundle, history, upcoming, now=now)
    counters = {"inserted": 0, "frozen": 0, "too_late": 0}
    for p, um in zip(preds, upcoming):
        status = ledger.insert_prediction(
            match_id=p["match_id"], start_ts=um.start_ts,
            team1=p["team1"], team2=p["team2"],
            team1_name=p["team1_name"], team2_name=p["team2_name"],
            event=p["event"], best_of=p["best_of"],
            p_model=p["p_model"], p_elo=p["p_elo"],
            model_version=p["model_version"], low_history=p["low_history"],
            now=now)
        counters[status] += 1
    json_path = json_path or (config.PROCESSED_DIR / "upcoming_predictions.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps({
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "model_version": bundle.get("version", "unknown"),
        "pool": preds[0]["pool"] if preds else [],
        "predictions": preds,
    }, indent=1), encoding="utf-8")
    log.info("predictions: %s", counters)
    return counters
