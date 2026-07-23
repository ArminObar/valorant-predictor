"""Assemble the training matrix.

One row per (completed match, map), oriented so team A = as-listed team1.
Every statistic is computed by the as-of engine and the event-queue EloBook at
the match's start time, so nothing dated at-or-after a match's start can enter
its features. That claim is enforced twice:
- tests/test_leakage.py poisons the future and asserts feature equality;
- `build_features` itself re-derives a random sample of rows against a
  hard-truncated history at build time and refuses to proceed on any mismatch.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd

from .. import config
from ..data.store import is_playoff
from ..modeling.baselines import compute_prematch_elo, elo_snapshot_at, matches_lite_from_maps
from .asof import AsOfEngine, TIER_A_DIFFS, TIER_B_DIFFS, add_est_end, snapshot_diffs

log = logging.getLogger("vpredict.build")

CONTEXT_FEATURES = ["best_of", "playoff", "hist_min"]


@dataclass
class FeatureSet:
    X: pd.DataFrame
    y: pd.Series
    meta: pd.DataFrame
    feature_names: list[str]
    dropped_tier_b: list[str]
    params: dict = field(default_factory=dict)

    def save(self, path=None) -> str:
        path = path or (config.PROCESSED_DIR / "features.joblib")
        joblib.dump(self, path)
        return str(path)

    @staticmethod
    def load(path=None) -> "FeatureSet":
        return joblib.load(path or (config.PROCESSED_DIR / "features.joblib"))


def _assemble_row(diffs: dict, elo_entry: dict, map_name: str,
                  best_of: int, playoff: bool, hist_min: float) -> dict:
    eff_a, eff_b = elo_entry["maps"][map_name]
    row = {
        "elo_diff": elo_entry["elo_a"] - elo_entry["elo_b"],
        "map_elo_diff": eff_a - eff_b,
        **diffs,
        "best_of": float(best_of),
        "playoff": float(playoff),
        "hist_min": hist_min,
    }
    return row


def build_features(
    maps_df: pd.DataFrame,
    *,
    half_life_days: float = config.DEFAULT_HALF_LIFE_DAYS,
    roster_factor: float = config.DEFAULT_ROSTER_FACTOR,
    elo_k: float = config.DEFAULT_ELO_K,   # fixed for FEATURES; baseline K is tuned separately
    tier_b: str | bool = "auto",           # "auto" | True | False
    min_history: int = config.MIN_MAPS_HISTORY,
    spot_checks: int = config.LEAKAGE_SPOT_CHECKS,
    seed: int = config.RANDOM_SEED,
) -> FeatureSet:
    if maps_df.empty:
        raise ValueError("maps_df is empty — scrape data first (make scrape) or run make demo")
    lites = matches_lite_from_maps(maps_df)
    elo_table = compute_prematch_elo(lites, k=elo_k)
    engine = AsOfEngine(maps_df, half_life_days=half_life_days, roster_factor=roster_factor)

    feat_rows: list[dict] = []
    meta_rows: list[dict] = []
    ys: list[int] = []
    for lite in lites:
        cutoff = lite["start_ts"]
        snap_a = engine.team_snapshot(lite["a"], cutoff)
        snap_b = engine.team_snapshot(lite["b"], cutoff)
        if min(snap_a.n_maps, snap_b.n_maps) < min_history:
            continue
        diffs = snapshot_diffs(snap_a, snap_b)
        hist_min = math.log1p(min(snap_a.n_maps, snap_b.n_maps))
        playoff = is_playoff(lite["series"])
        entry = elo_table[lite["match_id"]]
        for map_name, a_won, map_index in lite["maps"]:
            feat_rows.append(_assemble_row(diffs, entry, map_name,
                                           lite["best_of"], playoff, hist_min))
            ys.append(a_won)
            meta_rows.append({
                "match_id": lite["match_id"], "start_ts": cutoff,
                "map_name": map_name or "Unknown", "map_index": map_index,
                "team_a": lite["a"], "team_b": lite["b"],
                "team_a_name": lite["a_name"], "team_b_name": lite["b_name"],
                "best_of": lite["best_of"], "event": lite["event"],
                "series": lite["series"], "synthetic": lite["synthetic"],
                "n_hist_a": snap_a.n_maps, "n_hist_b": snap_b.n_maps,
            })

    if not feat_rows:
        raise ValueError(
            f"No usable rows: every match failed the >= {min_history} prior-maps "
            "filter. Scrape a longer window.")

    X = pd.DataFrame(feat_rows)
    y = pd.Series(ys, name="a_won", dtype=int)
    meta = pd.DataFrame(meta_rows)

    # ---- Tier B handling: auto-drop columns that are absent or too sparse.
    dropped: list[str] = []
    for c in TIER_B_DIFFS:
        cov = X[c].notna().mean() if c in X else 0.0
        keep = (tier_b is True and cov > 0) or (tier_b == "auto" and cov >= 0.9)
        if keep:
            X[c] = X[c].astype(float).fillna(0.0)
        else:
            if c in X:
                X = X.drop(columns=[c])
            dropped.append(c)
    if dropped:
        log.info("Tier B columns dropped (absent/sparse or disabled): %s", dropped)

    # ---- Map identity dummies (fixed order comes from feature_names).
    dummies = pd.get_dummies(meta["map_name"], prefix="map").astype(float)
    X = pd.concat([X.reset_index(drop=True), dummies.reset_index(drop=True)], axis=1)

    base = ["elo_diff", "map_elo_diff"] + TIER_A_DIFFS + \
        [c for c in TIER_B_DIFFS if c not in dropped]
    feature_names = base + CONTEXT_FEATURES + sorted(dummies.columns)
    X = X[feature_names].astype(float)

    fs = FeatureSet(
        X=X, y=y, meta=meta, feature_names=feature_names, dropped_tier_b=dropped,
        params={"half_life_days": half_life_days, "roster_factor": roster_factor,
                "elo_k_features": elo_k, "min_history": min_history,
                "tier_b": tier_b},
    )
    if spot_checks:
        _leakage_spot_check(fs, maps_df, n=spot_checks, seed=seed)
    return fs


# --------------------------------------------------------------------------- spot check
def _recompute_row(maps_df: pd.DataFrame, fs: FeatureSet, i: int) -> pd.Series:
    """Recompute row i from a history hard-truncated at its cutoff."""
    m = fs.meta.iloc[i]
    cutoff = m["start_ts"]
    trunc = add_est_end(maps_df)
    trunc = trunc[trunc["est_end_ts"] <= cutoff].drop(columns=["est_end_ts"])
    if trunc.empty:
        raise RuntimeError("spot-check: truncated history unexpectedly empty")
    engine = AsOfEngine(trunc,
                        half_life_days=fs.params["half_life_days"],
                        roster_factor=fs.params["roster_factor"])
    snap_a = engine.team_snapshot(m["team_a"], cutoff)
    snap_b = engine.team_snapshot(m["team_b"], cutoff)
    diffs = snapshot_diffs(snap_a, snap_b)
    lites_trunc = matches_lite_from_maps(trunc)
    probe = {"a": m["team_a"], "b": m["team_b"],
             "maps": [(m["map_name"], 0, m["map_index"])]}
    entry = elo_snapshot_at(lites_trunc, cutoff, probe, k=fs.params["elo_k_features"])
    row = _assemble_row(diffs, entry, m["map_name"], m["best_of"],
                        is_playoff(m["series"]),
                        math.log1p(min(snap_a.n_maps, snap_b.n_maps)))
    for c in fs.dropped_tier_b:
        row.pop(c, None)
    for c in list(row):
        if row[c] is None:
            row[c] = 0.0
    for c in fs.feature_names:
        if c.startswith("map_") and c != "map_elo_diff":
            row[c] = 1.0 if c == f"map_{m['map_name']}" else 0.0
    return pd.Series(row)[fs.feature_names].astype(float)


def _leakage_spot_check(fs: FeatureSet, maps_df: pd.DataFrame,
                        n: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(fs.X), size=min(n, len(fs.X)), replace=False)
    for i in idx:
        expected = fs.X.iloc[int(i)]
        got = _recompute_row(maps_df, fs, int(i))
        if not np.allclose(expected.to_numpy(), got.to_numpy(), atol=1e-9, rtol=1e-9):
            bad = [c for c in fs.feature_names
                   if not math.isclose(expected[c], got[c], abs_tol=1e-9, rel_tol=1e-9)]
            raise RuntimeError(
                "LEAKAGE SPOT-CHECK FAILED for match "
                f"{fs.meta.iloc[int(i)]['match_id']} map "
                f"{fs.meta.iloc[int(i)]['map_name']}: columns {bad} differ when "
                "recomputed from truncated history. Refusing to continue.")
    log.info("leakage spot-check passed on %d random rows", len(idx))


# --------------------------------------------------------------------------- splits & augmentation
def chronological_split(
    meta: pd.DataFrame,
    train_frac: float = config.TRAIN_FRACTION,
    val_frac: float = config.VAL_FRACTION,
) -> dict[str, np.ndarray]:
    """Split on MATCHES (maps of one match never straddle a boundary),
    strictly by start time."""
    order = (meta[["match_id", "start_ts"]]
             .drop_duplicates("match_id")
             .sort_values(["start_ts", "match_id"]))
    mids = order["match_id"].to_list()
    n = len(mids)
    n_train = int(n * train_frac)
    n_val = int(n * val_frac)
    train_ids = set(mids[:n_train])
    val_ids = set(mids[n_train:n_train + n_val])
    test_ids = set(mids[n_train + n_val:])
    return {
        "train": meta["match_id"].isin(train_ids).to_numpy(),
        "val": meta["match_id"].isin(val_ids).to_numpy(),
        "test": meta["match_id"].isin(test_ids).to_numpy(),
        "boundaries": {
            "train_end": order.iloc[n_train - 1]["start_ts"] if n_train else None,
            "val_end": order.iloc[n_train + n_val - 1]["start_ts"] if n_val else None,
            "n_matches": {"train": len(train_ids), "val": len(val_ids), "test": len(test_ids)},
        },
    }


def augment_swapped(X: pd.DataFrame, y: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """Teach symmetry: append every row with teams swapped. All *_diff columns
    negate, context and map dummies stay, the label flips. TRAINING ONLY."""
    Xs = X.copy()
    for c in X.columns:
        if c.endswith("_diff"):
            Xs[c] = -Xs[c]
    X_aug = pd.concat([X, Xs], ignore_index=True)
    y_aug = pd.concat([y, 1 - y], ignore_index=True)
    return X_aug, y_aug
