"""Walk-forward backtest — the live system replayed over history, ONCE.

Walks chronologically from the warmup boundary to the end of the store,
producing for every completed match the SAME quantity the live ledger
freezes: the pre-veto, pool-mean series probability (and its Elo
counterpart), called at the last legal moment (start − freeze margin),
under a bundle retrained on the production cadence with the production
selection policy (rolling-origin + hysteresis).

Reuse is literal, not approximate:
  * every prediction goes through modeling.predict.predict_one — the same
    function live serving calls — over an AsOfEngine + Elo replay whose
    cutoffs admit only matches whose ESTIMATED FINISH precedes the call;
  * every retrain is the same sequence train_and_save runs
    (chronological_split → rolling_origin_scores → choose_family →
    select_model → tune_elo_k), on the prebuilt feature matrix sliced to
    matches finished by the retrain moment. Slicing equals rebuilding:
    each row's features depend only on matches finishing before that row's
    own start (the leakage rule), so rows before the cutoff are identical
    either way.

Section discipline (spec item 7): the output is labeled BACKTEST —
simulated, large-sample, not independently verifiable — and is never
merged with the LIVE frozen-ledger section. Metrics are reported per event
tier only; counts live in the window block.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .. import config
from ..data.schema import Match
from ..features.asof import AsOfEngine, add_est_end
from ..features.build import (FeatureSet, augment_swapped, build_features,
                              chronological_split)
from ..modeling.baselines import matches_lite_from_maps, tune_elo_k
from ..modeling.predict import current_pool, predict_one
from ..modeling.train import (_family, choose_family, ll,
                              rolling_origin_scores, select_model)
from .tiers import classify_tier

log = logging.getLogger("vpredict.backtest")


def match_table(maps_df: pd.DataFrame) -> pd.DataFrame:
    """One row per match, derived entirely from the maps frame: teams (from
    the is_team1 orientation), winner by maps won, maps played, estimated
    end (same rule as everywhere: start + assumed duration by best-of)."""
    t1 = maps_df[maps_df["is_team1"]]
    first = t1.sort_values(["match_id", "map_index"]).groupby(
        "match_id", sort=False).first()
    wins = t1.groupby("match_id")["won"].sum()
    n_maps = t1.groupby("match_id")["won"].size()
    mt = pd.DataFrame({
        "match_id": first.index,
        "start_ts": first["start_ts"],
        "best_of": first["best_of"],
        "event": first["event"],
        "series": first["series"],
        "team1": first["team"], "team1_name": first["team_name"],
        "team2": first["opp"], "team2_name": first["opp_name"],
        "synthetic": first.get("synthetic", pd.Series(False, index=first.index)),
        "maps_played": n_maps,
        "team1_won": (wins > (n_maps - wins)).astype(int),
        "decided": wins != (n_maps - wins),
    }).reset_index(drop=True)
    mt = add_est_end(mt)
    return mt.sort_values(["start_ts", "match_id"]).reset_index(drop=True)


def _retrain(fs: FeatureSet, lites: list[dict], slice_ids: set,
             cutoff: pd.Timestamp, incumbent_family: str | None,
             index: int) -> tuple[dict, dict]:
    """One production-shaped retrain at `cutoff`, mirroring train_and_save
    step for step on the sliced rows. Returns (bundle, log_entry)."""
    mask = fs.meta["match_id"].isin(slice_ids).to_numpy()
    idx = np.where(mask)[0]
    sub_meta = fs.meta.iloc[idx].reset_index(drop=True)
    splits = chronological_split(sub_meta)
    g_tr = idx[splits["train"]]
    g_va = idx[splits["val"]]
    y = fs.y.to_numpy()
    n_train = int(sub_meta.loc[splits["train"], "match_id"].nunique())

    sel_idx = np.concatenate([g_tr, g_va])          # chronological: idx sorted
    sel_idx.sort()
    decision = choose_family(
        rolling_origin_scores(
            fs.X.iloc[sel_idx].reset_index(drop=True),
            y[sel_idx], n_train, augment=augment_swapped),
        incumbent_family)
    X_tr, y_tr = augment_swapped(fs.X.iloc[g_tr], fs.y.iloc[g_tr])
    sel = select_model(X_tr, y_tr, fs.X.iloc[g_va], y[g_va], n_train,
                       families=[decision["chosen"]])

    lites_t = [l for l in lites if l["est_end_ts"] <= cutoff]
    best_k, _, _ = tune_elo_k(lites_t, sub_meta, y[idx], splits["val"])

    bundle = {
        "model": sel["model"], "calibrator": sel["calibrator"],
        "cal_name": sel["cal_name"], "name": sel["name"],
        "feature_names": fs.feature_names, "params": fs.params,
        "elo_k_baseline": float(best_k),
        "version": f"backtest-r{index:02d}-{sel['name']}",
    }
    entry = {"t": cutoff.isoformat(), "index": index,
             "n_slice_matches": len(slice_ids), "n_train_matches": n_train,
             "chosen": decision["chosen"], "rule": decision["rule"],
             "margin_se": decision.get("margin_se"),
             "model": sel["name"], "val_ll": round(sel["val_ll"], 4),
             # Which calibrator, on how many rows: the validation run
             # surfaced an isotonic saturation episode right at the
             # admission boundary (LOG entry 31), so the walk records
             # enough to spot the next one without a reproduction.
             "calibrator": sel["cal_name"], "n_val_rows": int(len(g_va)),
             "elo_k": float(best_k)}
    return bundle, entry


def run_backtest(maps_df: pd.DataFrame, *,
                 features: FeatureSet | None = None,
                 warmup_matches: int = 300,
                 tick_hours: int = 6,
                 feature_params: dict | None = None,
                 progress=None) -> tuple[dict, list[dict]]:
    """Returns (report, rows). `rows` is the full per-match audit record
    (ledger-shaped); `report` is the per-tier summary the site serves."""
    fp = {"half_life_days": config.DEFAULT_HALF_LIFE_DAYS,
          "roster_factor": config.DEFAULT_ROSTER_FACTOR,
          **(feature_params or {})}
    fs = features or build_features(maps_df, **fp)
    if (fs.params["half_life_days"], fs.params["roster_factor"]) != \
            (fp["half_life_days"], fp["roster_factor"]):
        raise ValueError("feature cache params differ from requested params; "
                         "rebuild the cache or drop --features-cache")
    engine = AsOfEngine(maps_df, half_life_days=fp["half_life_days"],
                        roster_factor=fp["roster_factor"])
    lites = matches_lite_from_maps(maps_df)
    mt = match_table(maps_df)
    if len(mt) <= warmup_matches:
        raise ValueError(f"only {len(mt)} matches; warmup needs more than "
                         f"{warmup_matches}")

    ends = mt["est_end_ts"].sort_values().reset_index(drop=True)
    completed_at = lambda t: int(ends.searchsorted(t, side="right"))
    warmup_t = ends.iloc[warmup_matches - 1]
    tick = pd.Timedelta(hours=tick_hours)
    freeze = pd.Timedelta(seconds=config.LEDGER_FREEZE_MARGIN_S)
    max_age = pd.Timedelta(days=config.RETRAIN_MAX_AGE_DAYS)

    bundle = None
    incumbent = None
    retrains: list[dict] = []
    last_train_t = None
    n_at_last = 0
    next_tick = warmup_t
    rows: list[dict] = []
    n_skipped_warmup = 0

    def maybe_retrain(upto: pd.Timestamp) -> None:
        nonlocal bundle, incumbent, last_train_t, n_at_last, next_tick
        while next_tick <= upto:
            t = next_tick
            next_tick = next_tick + tick
            fire, why = False, ""
            if bundle is None:
                fire, why = True, f"warmup ({warmup_matches} matches finished)"
            elif t - last_train_t >= max_age:
                fire, why = True, f"bundle older than {config.RETRAIN_MAX_AGE_DAYS}d"
            elif completed_at(t) - n_at_last >= config.RETRAIN_NEW_MATCHES:
                fire, why = True, f"{completed_at(t) - n_at_last} new matches"
            if fire:
                slice_ids = set(mt.loc[mt["est_end_ts"] <= t, "match_id"])
                b, entry = _retrain(fs, lites, slice_ids, t, incumbent,
                                    index=len(retrains) + 1)
                entry["trigger"] = why
                bundle, incumbent = b, _family(b["name"])
                retrains.append(entry)
                last_train_t, n_at_last = t, completed_at(t)
                log.info("retrain %d at %s: %s (%s)", entry["index"], t,
                         entry["model"], why)

    it = mt.itertuples(index=False)
    for i, m in enumerate(it):
        call_ts = pd.Timestamp(m.start_ts) - freeze
        maybe_retrain(call_ts)
        if bundle is None:
            n_skipped_warmup += 1
            continue
        um = Match(match_id=m.match_id, start_ts=m.start_ts,
                   status="upcoming", best_of=int(m.best_of),
                   event=m.event or "", series=m.series or "",
                   team1_id=m.team1, team1_name=m.team1_name,
                   team2_id=m.team2, team2_name=m.team2_name,
                   synthetic=bool(m.synthetic))
        pool = current_pool(maps_df, call_ts)
        pred = predict_one(bundle, engine, lites, pool, um, call_ts)
        pred.update({
            "made_at": call_ts.isoformat(),
            "tier": classify_tier(m.event or ""),
            "graded": bool(m.decided),
            "team1_won": int(m.team1_won) if m.decided else None,
            "maps_played": int(m.maps_played),
            "retrain_index": retrains[-1]["index"],
        })
        rows.append(pred)
        if progress and (len(rows) % 250 == 0):
            progress(len(rows))

    report = _build_report(rows, retrains, mt, warmup_matches, tick_hours,
                           n_skipped_warmup, fp)
    return report, rows


def _metrics(rs: list[dict]) -> dict:
    y = np.array([r["team1_won"] for r in rs], dtype=float)
    pm = np.array([r["p_model"] for r in rs], dtype=float)
    pe = np.array([r["p_elo"] for r in rs], dtype=float)
    return {
        "n_scored": len(rs),
        "model_ll": round(ll(y, pm), 4),
        "model_brier": round(float(np.mean((pm - y) ** 2)), 4),
        "model_acc": round(float(np.mean((pm > 0.5) == y)), 4),
        "elo_ll": round(ll(y, pe), 4),
        "elo_brier": round(float(np.mean((pe - y) ** 2)), 4),
        "elo_acc": round(float(np.mean((pe > 0.5) == y)), 4),
    }


def _period(made_at: str) -> str:
    ts = pd.Timestamp(made_at)
    return f"{ts.year}H{1 if ts.month <= 6 else 2}"


def summarize_rows(rows: list[dict]) -> dict:
    """Per-tier metric blocks from the audit rows — shared by the walk's
    report and by --rebuild-report, so a report-format change never forces
    a re-walk (run-once stays intact). Metrics per tier only; the
    by-period split answers "is the edge stationary?" within each tier and
    is never pooled across tiers either."""
    graded = [r for r in rows if r["graded"]]
    scored = [r for r in graded if not r["low_history"]]
    per_tier: dict[str, dict] = {}
    by_period: dict[str, dict] = {}
    for tier in sorted({r["tier"] for r in rows}):
        t_scored = [r for r in scored if r["tier"] == tier]
        entry = _metrics(t_scored) if t_scored else {"n_scored": 0}
        entry["n_predictions"] = sum(r["tier"] == tier for r in rows)
        entry["n_low_history"] = sum(
            r["tier"] == tier and r["low_history"] for r in graded)
        per_tier[tier] = entry
        by_period[tier] = {
            per: _metrics(prs)
            for per in sorted({_period(r["made_at"]) for r in t_scored})
            if (prs := [r for r in t_scored if _period(r["made_at"]) == per])
        }
    return {"per_tier": per_tier, "per_tier_by_period": by_period}


def rebuild_report(rows: list[dict], old_summary: dict,
                   rows_file: str) -> dict:
    """New summary from frozen audit rows: metric blocks recomputed, the
    walk's own record (window, protocol, retrains, versions) carried over
    verbatim. No prediction is recomputed."""
    out = dict(old_summary)
    out.update(summarize_rows(rows))
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    out["rebuilt_from_rows"] = rows_file
    return out


def _build_report(rows: list[dict], retrains: list[dict], mt: pd.DataFrame,
                  warmup_matches: int, tick_hours: int,
                  n_skipped_warmup: int, fp: dict) -> dict:
    graded = [r for r in rows if r["graded"]]
    blocks = summarize_rows(rows)
    return {
        "section": "BACKTEST",
        "label": ("simulated walk-forward. Large sample, not independently "
                  "verifiable, never merged with the LIVE frozen ledger."),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_data": bool(mt["synthetic"].any()),
        "protocol": {
            "quantity": ("pre-veto pool-mean series probability, the same "
                         "quantity the live ledger freezes"),
            "call_time": "start minus freeze margin (the latest legal call)",
            "freeze_margin_s": config.LEDGER_FREEZE_MARGIN_S,
            "cadence": {"max_age_days": config.RETRAIN_MAX_AGE_DAYS,
                        "new_matches": config.RETRAIN_NEW_MATCHES,
                        "tick_hours": tick_hours},
            "warmup_matches": warmup_matches,
            "selection": "rolling5-expanding + 1SE-hysteresis per retrain",
            "metrics_rows": ("graded, non-low-history predictions "
                             "(low-history rows are made and counted, per "
                             "the live ledger, but not scored)"),
            "feature_params": fp,
        },
        "window": {
            "first_prediction": rows[0]["made_at"] if rows else None,
            "last_prediction": rows[-1]["made_at"] if rows else None,
            "n_predictions": len(rows),
            "n_graded": len(graded),
            "n_low_history": sum(r["low_history"] for r in graded),
            "n_skipped_warmup": n_skipped_warmup,
            "n_retrains": len(retrains),
        },
        "per_tier": blocks["per_tier"],
        "per_tier_by_period": blocks["per_tier_by_period"],
        "retrains": retrains,
    }
