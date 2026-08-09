#!/usr/bin/env python3
"""Roster-continuity Phase-1 ablation (ASSUMPTIONS §66). The protocol and
decision rule were pre-registered in §66 BEFORE this ran; this script is
their implementation and the only source of the numbers it prints.

Reuses the shipped machinery verbatim: build_features (relaxed once per
arm), chronological_split, augment_swapped, select_model's gated menu
and calibration. Writes reports/roster_phase1-<date>.md.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from vpredict import config  # noqa: E402
from vpredict.data import store  # noqa: E402
from vpredict.data.schema import Match  # noqa: E402
from vpredict.evaluation.tiers import classify_tier  # noqa: E402
from vpredict.features.build import (augment_swapped, build_features,  # noqa: E402
                                     chronological_split)
from vpredict.modeling.train import ll, predict_calibrated, select_model  # noqa: E402


def _metrics(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return {"n": int(len(y)), "ll": round(ll(y, p), 4),
            "brier": round(float(np.mean((p - y) ** 2)), 4),
            "acc": round(float(np.mean((p >= 0.5) == (y == 1))), 4)}


def run_arm(maps_df: pd.DataFrame, roster: bool) -> dict:
    fs = build_features(maps_df, roster_continuity=roster, min_history=0)
    hist_min_maps = fs.meta[["n_hist_a", "n_hist_b"]].min(axis=1)
    std = (hist_min_maps >= config.MIN_MAPS_HISTORY).to_numpy()
    lowh = ~std

    split = chronological_split(fs.meta[std].reset_index(drop=True))
    Xs = fs.X[std].reset_index(drop=True)
    ys = fs.y[std].reset_index(drop=True)
    ms = fs.meta[std].reset_index(drop=True)
    tr, va, te = split["train"], split["val"], split["test"]

    X_tr, y_tr = augment_swapped(Xs.iloc[tr], ys.iloc[tr])
    n_train_matches = ms.iloc[tr]["match_id"].nunique()
    sel = select_model(X_tr, y_tr, Xs.iloc[va], ys.iloc[va],
                       n_train_matches)

    # Low-history rows join the SAME time windows by match start.
    bounds = {k: (ms.iloc[idx]["start_ts"].min(),
                  ms.iloc[idx]["start_ts"].max())
              for k, idx in (("val", va), ("test", te))}
    Xl = fs.X[lowh].reset_index(drop=True)
    yl = fs.y[lowh].reset_index(drop=True)
    ml = fs.meta[lowh].reset_index(drop=True)

    out = {"selected": sel["name"], "cal": sel["cal_name"],
           "gate": sel["gate_note"],
           "candidates": sel["candidate_val_ll"],
           "n_rows_std": int(std.sum()), "n_rows_lowh": int(lowh.sum())}
    for slice_name, idx in (("val", va), ("test", te)):
        p = predict_calibrated(sel, Xs.iloc[idx])
        out[slice_name] = _metrics(ys.iloc[idx], p)
        tiers = ms.iloc[idx]["event"].map(classify_tier)
        out[f"{slice_name}_by_tier"] = {
            t: _metrics(ys.iloc[idx][tiers.values == t],
                        p[tiers.values == t])
            for t in sorted(tiers.unique())}
        lo_mask = ((ml["start_ts"] >= bounds[slice_name][0])
                   & (ml["start_ts"] <= bounds[slice_name][1])).to_numpy()
        if lo_mask.any():
            pl = predict_calibrated(sel, Xl[lo_mask])
            out[f"{slice_name}_lowh"] = _metrics(yl[lo_mask], pl)
        else:
            out[f"{slice_name}_lowh"] = {"n": 0}
    if roster:
        out["roster_cols_nonzero"] = {
            c: round(float((fs.X[c] != 0).mean()), 3)
            for c in ("roster_ext_maps_diff", "roster_coplay_diff")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(config.MATCHES_JSONL))
    ap.add_argument("--reports", default=str(config.REPORTS_DIR))
    args = ap.parse_args()

    t0 = time.time()
    src = Path(args.data)
    opener = gzip.open if src.suffix == ".gz" else open
    matches = [Match(**json.loads(l))
               for l in opener(src, "rt") if l.strip()]
    maps_df = store.maps_frame(matches)
    if bool(maps_df.get("synthetic", pd.Series(dtype=bool)).any()):
        print("SYNTHETIC DATA PRESENT — this run is not reportable")
    arms = {"off": run_arm(maps_df, roster=False),
            "on": run_arm(maps_df, roster=True)}

    off, on = arms["off"], arms["on"]
    primary = (on["val_lowh"].get("n", 0) > 0
               and on["val_lowh"]["ll"] < off["val_lowh"]["ll"])
    guard = on["val"]["ll"] <= off["val"]["ll"] + 0.001
    ship = bool(primary and guard)
    verdict = ("SHIP default ON" if ship else "default stays OFF")

    lines = [
        "# Roster-continuity Phase-1 ablation",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat()[:16]} UTC by "
        "`scripts/ablate_roster.py` (protocol and decision rule "
        "pre-registered in ASSUMPTIONS §66 before the run).",
        "",
        f"- Matches: {len(matches)}; standard rows "
        f"{off['n_rows_std']}, low-history rows {off['n_rows_lowh']}",
        f"- Arm OFF: selected {off['selected']} + {off['cal']} "
        f"(candidates {off['candidates']})",
        f"- Arm ON:  selected {on['selected']} + {on['cal']} "
        f"(candidates {on['candidates']}); roster col nonzero "
        f"{on.get('roster_cols_nonzero')}",
        "",
        "## Validation (selection window)",
        "",
        "| slice | arm | n | log loss | brier | acc |",
        "|---|---|---|---|---|---|",
    ]
    for slice_name in ("val", "val_lowh", "test", "test_lowh"):
        for arm_name in ("off", "on"):
            m = arms[arm_name][slice_name]
            if m.get("n"):
                lines.append(
                    f"| {slice_name} | {arm_name} | {m['n']} | "
                    f"{m['ll']} | {m['brier']} | {m['acc']} |")
            else:
                lines.append(f"| {slice_name} | {arm_name} | 0 | — | — | — |")
    lines += ["", "## Validation by tier (map grain)", "",
              "| tier | off LL (n) | on LL (n) |", "|---|---|---|"]
    for t in sorted(off["val_by_tier"]):
        a = off["val_by_tier"][t]
        b = on["val_by_tier"].get(t, {})
        lines.append(f"| {t} | {a['ll']} ({a['n']}) | "
                     f"{b.get('ll', '—')} ({b.get('n', 0)}) |")
    lines += [
        "",
        "## Decision (rule fixed in §66 before the run)",
        "",
        f"- Primary (low-history val LL improves): "
        f"{'MET' if primary else 'NOT MET'} "
        f"(off {off['val_lowh'].get('ll')} vs on "
        f"{on['val_lowh'].get('ll')})",
        f"- Guard (overall val LL not worse by >0.001): "
        f"{'MET' if guard else 'NOT MET'} "
        f"(off {off['val']['ll']} vs on {on['val']['ll']})",
        f"- Verdict: **{verdict}**",
        "",
        "Test rows above are a disclosed second read of the same window "
        "results-2yr used; validation decided, test is the record. "
        f"Runtime {time.time()-t0:.0f}s.",
    ]
    out_dir = Path(args.reports)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"roster_phase1-{datetime.now().date().isoformat()}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
