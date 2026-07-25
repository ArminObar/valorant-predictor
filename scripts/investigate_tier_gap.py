#!/usr/bin/env python3
"""Tier-gap investigation (owner request, 2026-07-24 night). REPORT ONLY.

Two questions, answered on TRAIN + VALIDATION rows exclusively — the test
window is never read, and that is asserted structurally, not promised.

A) Oracle stand-in ceiling. Can knowing the ACTUAL lineup of the match
   being predicted (which serving cannot know pre-match from vlr data)
   improve on the shipped as-of proxies? Per row, the oracle feature is
   the share of the actually-fielded lineup outside the team's as-of
   5-player core, differenced A−B. Fit LR with and without it on train,
   compare on validation, overall and per tier. This is a deliberate
   leak-by-design UPPER BOUND on what any roster-news data source could
   ever contribute; it is never shippable and says so.

B) Tier-1 learning curve. Fit LR on growing chronological prefixes of
   train, score a FIXED validation window (overall / tier1 / tier2)
   against the as-of Elo reference. A flat curve at full data argues the
   Elo gap is structural at current features; a descending one supports
   "more data closes it" with an arithmetic ETA at ~65 matches/week.

Every number prints from this script; nothing is written to reports.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from vpredict import config
from vpredict.data import store
from vpredict.evaluation.tiers import classify_tier
from vpredict.features.asof import AsOfEngine
from vpredict.features.build import (FeatureSet, augment_swapped,
                                     chronological_split)
from vpredict.modeling.baselines import (compute_prematch_elo,
                                         matches_lite_from_maps)
from vpredict.modeling.train import fit_lr, ll


def main() -> int:
    fs = FeatureSet.load("data/processed/features_cache.parquet")
    maps_df = store.maps_frame(store.iter_matches(config.MATCHES_JSONL))
    engine = AsOfEngine(maps_df)
    splits = chronological_split(fs.meta)
    tr, va, te = splits["train"], splits["val"], splits["test"]
    assert not (np.asarray(tr) & np.asarray(te)).any()
    assert not (np.asarray(va) & np.asarray(te)).any()
    used = np.asarray(tr) | np.asarray(va)
    y = fs.y.to_numpy()
    tiers = fs.meta["event"].map(classify_tier).to_numpy()

    # As-of Elo reference (K=24, the production baseline), leak-free by
    # construction; identical across every arm below.
    lites = matches_lite_from_maps(maps_df)
    table = compute_prematch_elo(lites, k=24)
    p_elo = np.array([table[m]["p_a"] for m in fs.meta["match_id"]])

    # ---------------- A. oracle stand-in ceiling (train+val rows only)
    lineup_of = {}
    for r in maps_df.itertuples():
        lineup_of[(r.match_id, r.map_name, r.team)] = set(r.lineup or [])
    core_cache: dict[tuple, set] = {}

    def core(team: str, cutoff) -> set:
        key = (team, cutoff)
        if key not in core_cache:
            g = engine.eligible(team, pd.Timestamp(cutoff))
            core_cache[key] = AsOfEngine._core_roster(g) or set()
        return core_cache[key]

    oracle = np.zeros(len(fs.meta))
    for i, r in enumerate(fs.meta.itertuples()):
        if not used[i]:
            continue                     # test rows never even computed
        la = lineup_of.get((r.match_id, r.map_name, r.team_a), set())
        lb = lineup_of.get((r.match_id, r.map_name, r.team_b), set())
        ca, cb = core(r.team_a, r.start_ts), core(r.team_b, r.start_ts)
        oa = len(la - ca) / max(len(la), 1) if ca else 0.0
        ob = len(lb - cb) / max(len(lb), 1) if cb else 0.0
        oracle[i] = oa - ob

    shipped = fs.X["core_absent_diff"].to_numpy()
    corr = np.corrcoef(oracle[used], shipped[used])[0, 1]
    n_events = int((np.abs(oracle[used]) > 1e-9).sum())
    print(f"[A] oracle stand-in events on train+val rows: {n_events}"
          f"/{int(used.sum())} ({n_events/used.sum()*100:.1f}%); "
          f"corr(oracle, shipped core_absent_diff) = {corr:+.3f}")

    Xb = fs.X
    Xo = fs.X.copy()
    Xo["oracle_standin_diff"] = oracle
    X_trb, y_trb = augment_swapped(Xb[tr], fs.y[tr])
    X_tro, y_tro = augment_swapped(Xo[tr], fs.y[tr])
    base = fit_lr(X_trb, y_trb, Xb[va], y[va])
    orac = fit_lr(X_tro, y_tro, Xo[va], y[va])
    pb = base["model"].predict_proba(Xb[va])[:, 1]
    po = orac["model"].predict_proba(Xo[va])[:, 1]
    yv = y[va]
    tv = tiers[va]
    print(f"[A] validation LL   overall: base {ll(yv, pb):.4f} -> "
          f"oracle {ll(yv, po):.4f}  (elo {ll(yv, p_elo[va]):.4f})")
    for t in ("tier1", "tier2"):
        m = tv == t
        print(f"[A] validation LL   {t:6s}: base {ll(yv[m], pb[m]):.4f} -> "
              f"oracle {ll(yv[m], po[m]):.4f}  "
              f"(elo {ll(yv[m], p_elo[va][m]):.4f}, n={int(m.sum())})")

    # ---------------- B. tier-1 learning curve on the fixed validation
    idx_tr = np.where(tr)[0]
    print("\n[B] LR trained on growing chronological prefixes of TRAIN, "
          "scored on the fixed validation window:")
    print("    prefix  n_rows   val LL all  (elo)    val LL tier1 (elo)"
          "    val LL tier2 (elo)")
    for frac in (0.25, 0.5, 0.75, 1.0):
        cut = idx_tr[: int(len(idx_tr) * frac)]
        Xf, yf = augment_swapped(fs.X.iloc[cut], fs.y.iloc[cut])
        m = fit_lr(Xf, yf, fs.X[va], y[va])
        pv = m["model"].predict_proba(fs.X[va])[:, 1]
        row = [f"    {int(frac*100):3d}%  {len(cut):6d}  "
               f"{ll(yv, pv):.4f} ({ll(yv, p_elo[va]):.4f})"]
        for t in ("tier1", "tier2"):
            mk = tv == t
            row.append(f"   {ll(yv[mk], pv[mk]):.4f} "
                       f"({ll(yv[mk], p_elo[va][mk]):.4f})")
        print("".join(row))
    n_t1 = int((fs.meta["event"].map(classify_tier) == "tier1")
               [np.asarray(tr)].sum())
    print(f"\n[B] tier1 map rows in train: {n_t1}; usable tier1 accrual "
          f"~12-13 matches/week at the current ~65/week crawl rate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
