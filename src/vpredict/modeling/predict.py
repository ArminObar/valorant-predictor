"""Predict upcoming matches with the trained bundle.

Pre-veto series probability: per-map calibrated probabilities are computed for
every map in the CURRENT pool (top-N maps by recency-weighted play frequency —
half-life CURRENT_POOL_HALF_LIFE_DAYS — over the last CURRENT_POOL_WINDOW_DAYS),
averaged with uniform pool weights (documented simplification — real pick/ban
tendencies are future work), and pushed through the exact best-of DP. The as-of cutoff is NOW: only matches whose estimated
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


def pool_table(maps_df: pd.DataFrame, now: pd.Timestamp,
               window_days: int = config.CURRENT_POOL_WINDOW_DAYS,
               half_life_days: float | None = config.CURRENT_POOL_HALF_LIFE_DAYS,
               ) -> pd.DataFrame:
    """One row per map with plays finished before `now` and started inside the
    window: raw play count, recency-weighted count, and last start time.

    Each play is weighted 0.5 ** (age_days / half_life_days), age taken from
    its start. Raw 60-day frequency kept rotated-out maps in the served pool
    for weeks after the 2026-06-24 rotation (ASSUMPTIONS §36); the half-life
    lets a rotation phase in within a couple of weeks while the window stays a
    hard support bound. `half_life_days` of None or <= 0 restores raw counts.
    Sorted by weighted count descending, ties alphabetical — deterministic.
    The weighting chooses pool MEMBERSHIP only; averaging across the chosen
    pool remains uniform (module docstring)."""
    df = add_est_end(maps_df)
    finished = df[df["est_end_ts"] <= now]
    recent = finished[finished["start_ts"] >= now - pd.Timedelta(days=window_days)]
    if recent.empty:
        recent = finished
    plays = recent[recent["is_team1"]]
    if plays.empty:
        return pd.DataFrame(
            {"plays": pd.Series(dtype=int),
             "weighted": pd.Series(dtype=float),
             "last_played": pd.Series(dtype="datetime64[us, UTC]")})
    age_days = (now - plays["start_ts"]).dt.total_seconds() / 86400.0
    if half_life_days and half_life_days > 0:
        w = 0.5 ** (age_days / float(half_life_days))
    else:
        w = pd.Series(1.0, index=plays.index)
    tbl = (pd.DataFrame({"map_name": plays["map_name"].to_numpy(),
                         "w": w.to_numpy(),
                         "start": plays["start_ts"].to_numpy()})
           .groupby("map_name")
           .agg(plays=("w", "size"), weighted=("w", "sum"),
                last_played=("start", "max")))
    # groupby sorts the index alphabetically; a stable sort on top makes
    # equal-weight ties come out alphabetical rather than order-of-appearance.
    return tbl.sort_values("weighted", ascending=False, kind="mergesort")


def current_pool(maps_df: pd.DataFrame, now: pd.Timestamp,
                 window_days: int = config.CURRENT_POOL_WINDOW_DAYS,
                 size: int = config.CURRENT_POOL_SIZE,
                 half_life_days: float | None = config.CURRENT_POOL_HALF_LIFE_DAYS,
                 ) -> list[str]:
    return pool_table(maps_df, now, window_days=window_days,
                      half_life_days=half_life_days).head(size).index.tolist()


def _elo_p(pair) -> float:
    ra, rb = pair
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / config.ELO_SCALE))


def _pub(x: float) -> float:
    """Publish a probability: round to the ledger precision, then clamp one
    rounding-ulp inside (0, 1). Series aggregation can push a map-clipped
    probability back within rounding distance of 1.0 (a Bo5 of 0.995s is
    0.999999), so the bound must sit at the published boundary, not only in
    the calibrator."""
    lo = 10.0 ** -config.PROB_DECIMALS
    return min(max(round(float(x), config.PROB_DECIMALS), lo), 1.0 - lo)


def predict_one(bundle: dict, engine: AsOfEngine, lites: list[dict],
                pool: list[str], um: Match, now_ts: pd.Timestamp) -> dict:
    """One pre-veto prediction at cutoff `now_ts` — the shared body of live
    serving and the walk-forward backtest. All as-of discipline lives in the
    machinery this calls: engine snapshots and Elo replays admit only
    matches whose ESTIMATED FINISH precedes `now_ts`, so passing full
    history (including the target match itself and its future) is safe by
    construction — the same property the build-time leakage spot-check
    pins."""
    params = bundle["params"]
    feature_names = bundle["feature_names"]
    dummy_cols = [c for c in feature_names
                  if c.startswith("map_") and c != "map_elo_diff"]

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
    # Per-map Elo lean (feature-K, map-effective blend): the model's own
    # per-map input, surfaced so the UI can show map-specific signal even
    # when the isotonic calibrator snaps nearby raw scores onto one output
    # level and every pool map displays the same probability (LOG entry
    # 37). Display-only; never written to the ledger.
    per_map_elo = {m: round(float(e_feat["maps"][m][0] - e_feat["maps"][m][1]),
                            1)
                   for m in kept_maps}
    p_map_mean = float(p_maps.mean())
    dist = sr.series_outcome_dist([p_map_mean] * int(um.best_of))
    p_model = dist["p_win"]
    pe_maps = [_elo_p(e_base["maps"][m]) for m in kept_maps]
    pe_mean = float(sum(pe_maps) / len(pe_maps))
    p_elo = sr.series_prob([pe_mean] * int(um.best_of))

    return {
        "match_id": um.match_id,
        "start_ts": um.start_ts.isoformat(),
        "event": um.event, "series": um.series, "best_of": um.best_of,
        "team1": a, "team2": b,
        "team1_name": um.team1_name, "team2_name": um.team2_name,
        "p_model": _pub(p_model), "p_elo": _pub(p_elo),
        "maps_dist": {str(k): round(v, 4)
                      for k, v in sorted(dist["maps_dist"].items())},
        "per_map": {m: round(float(p), 4) for m, p in zip(kept_maps, p_maps)},
        "per_map_elo": per_map_elo,
        "pool": pool, "low_history": low_history,
        "model_version": bundle.get("version", "unknown"),
    }


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
    return [predict_one(bundle, engine, lites, pool, um, now_ts)
            for um in upcoming]


def _names_for_row(row: dict, um: Match) -> tuple[str, str, str]:
    """Current listing names mapped onto the FROZEN row's team order by key.

    The published payload shows the listing's names (reschedules and resolved
    TBDs must display) beside the ledger's probability, which is oriented to
    the ledger's team1. Pairing them positionally assumes the listing never
    swaps display order after the freeze — an assumption nothing enforced.
    Matching by key removes the assumption: a swapped listing swaps the
    names, an unmatchable listing (renamed key) falls back to the frozen
    names, and the probability's orientation can never be miscaptioned.
    Returns (team1_name, team2_name, status) with status in
    {"aligned", "swapped", "unmatched"}."""
    k1, k2 = str(row["team1"]), str(row["team2"])
    u1, u2 = str(um.key_team("team1")), str(um.key_team("team2"))
    if (u1, u2) == (k1, k2):
        return um.team1_name, um.team2_name, "aligned"
    if (u1, u2) == (k2, k1):
        return um.team2_name, um.team1_name, "swapped"
    return (row.get("team1_name") or um.team1_name,
            row.get("team2_name") or um.team2_name, "unmatched")


def run_predictions(bundle: dict, history, upcoming: list[Match],
                    ledger, now: datetime | None = None,
                    json_path=None) -> dict:
    """Predict what needs predicting, write the frozen ledger, and publish the
    JSON the API serves FROM THE LEDGER. The public payload carries the frozen
    first call for every match (LOG entry 44): the fresh model is consulted
    only for matches with no frozen row yet. Matches whose freeze window has
    passed without a row are not published at all — an uncalled match must
    never display as a call. Returns counters."""
    now = now or datetime.now(timezone.utc)
    json_path = json_path or (config.PROCESSED_DIR / "upcoming_predictions.json")
    # Unresolved bracket slots ("TBD vs TBD") collide to the SAME team key,
    # which is the model predicting a team against itself: p_elo is exactly
    # 0.5 and p_model is pure intercept bias. Skip them; the slot gets a
    # real prediction once the bracket resolves (new names, same freeze
    # rules). Rows frozen before this guard existed stand, get their names
    # backfilled at grade time, and are excluded from headline metrics by
    # the low-history scoring rule.
    playable = [um for um in upcoming
                if um.key_team("team1") != um.key_team("team2")]
    counters = {"inserted": 0, "frozen": 0, "too_late": 0,
                "skipped_placeholder": len(upcoming) - len(playable),
                "names_swapped": 0, "names_unmatched": 0}

    frozen_rows = {str(r["match_id"]): r
                   for r in ledger.rows(graded=None, limit=100000)}
    prev = {}
    prev_pool: list[str] = []
    if json_path.exists():
        try:
            old = json.loads(json_path.read_text())
            prev = {str(r.get("match_id")): r
                    for r in old.get("predictions", [])}
            prev_pool = old.get("pool", []) or []
        except ValueError:
            log.warning("previous %s unreadable; display extras rebuilt",
                        json_path)

    def _margin_ok(um: Match) -> bool:
        return ((um.start_ts - now).total_seconds()
                >= config.LEDGER_FREEZE_MARGIN_S)

    to_predict, publishable = [], []
    for um in playable:
        mid = str(um.match_id)
        if mid in frozen_rows:
            counters["frozen"] += 1
            publishable.append(um)
            if mid not in prev:      # display extras lost (fresh disk/deploy):
                to_predict.append(um)  # recompute per-map surface only
        elif _margin_ok(um):
            to_predict.append(um)
            publishable.append(um)
        else:
            counters["too_late"] += 1   # never called -> never displayed

    # The expensive engine build runs only when something actually needs it.
    preds = (predict_upcoming(bundle, history, to_predict, now=now)
             if to_predict else [])
    fresh = {}
    for pd_row, um in zip(preds, to_predict):
        fresh[str(um.match_id)] = pd_row
        if str(um.match_id) in frozen_rows:
            continue                      # display-only recompute, no insert
        status = ledger.insert_prediction(
            match_id=pd_row["match_id"], start_ts=um.start_ts,
            team1=pd_row["team1"], team2=pd_row["team2"],
            team1_name=pd_row["team1_name"], team2_name=pd_row["team2_name"],
            event=pd_row["event"], best_of=pd_row["best_of"],
            p_model=pd_row["p_model"], p_elo=pd_row["p_elo"],
            model_version=pd_row["model_version"],
            low_history=pd_row["low_history"],
            p_maps_dist=pd_row.get("maps_dist"), now=now)
        counters[status] += 1
        if status == "too_late":          # raced the margin since the check
            publishable.remove(um)

    # Re-read once so the payload can only contain what the ledger stored.
    frozen_rows = {str(r["match_id"]): r
                   for r in ledger.rows(graded=None, limit=100000)}

    published = []
    for um in publishable:
        mid = str(um.match_id)
        row = frozen_rows.get(mid)
        if row is None:                   # belt and braces; never publish
            continue                      # a call the record does not hold
        extras = fresh.get(mid) or prev.get(mid) or {}
        maps_dist = row.get("p_maps_dist")
        if isinstance(maps_dist, str):
            try:
                maps_dist = json.loads(maps_dist)
            except ValueError:
                maps_dist = None
        # Schedule and naming come from the CURRENT listing: reschedules
        # and resolved TBDs must display, and are metadata (§15) — but the
        # names are mapped onto the frozen row's team order by key (§55),
        # never trusted positionally.
        n1, n2, align = _names_for_row(row, um)
        if align != "aligned":
            counters[f"names_{align}"] += 1
            log.warning("match %s: listing team order %s vs frozen row",
                        um.match_id, align)
        published.append({
            "match_id": um.match_id,
            "start_ts": um.start_ts.isoformat(),
            "event": um.event, "series": um.series, "best_of": um.best_of,
            "team1": row["team1"], "team2": row["team2"],
            "team1_name": n1, "team2_name": n2,
            # The call itself comes from the LEDGER, verbatim.
            "p_model": row["p_model"], "p_elo": row["p_elo"],
            "low_history": bool(row["low_history"]),
            "model_version": row["model_version"],
            "maps_dist": maps_dist,
            # Display-only per-map surface (never in the ledger): frozen in
            # practice by carrying the first published values forward.
            "per_map": extras.get("per_map"),
            "per_map_elo": extras.get("per_map_elo"),
        })

    pool = (preds[0]["pool"] if preds else prev_pool)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps({
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "model_version": bundle.get("version", "unknown"),
        "pool": pool,
        "predictions": published,
    }, indent=1), encoding="utf-8")
    log.info("predictions: %s", counters)
    return counters
