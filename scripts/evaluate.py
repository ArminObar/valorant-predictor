#!/usr/bin/env python3
"""Reproduce every headline number from a single command.

    python scripts/evaluate.py [--data data/raw/matches.jsonl]

Sections (all chronological; the test window is untouched until reporting):
  1. Map-level: model vs constant / favourite / tuned-K Elo.
  2. Match-level: per-map probabilities aggregated over the veto into a
     series probability (unplayed deciders recovered from the veto note;
     mean-prob fallback counted, never silent).
  3. By event tier (tier1 VCT / tier2 Challengers / Game Changers / other).
  4. Tier-restriction experiment: train on tier-1 rows only vs all rows,
     evaluated on the identical held-out test windows.

If the data is synthetic (make demo), every output is loudly watermarked.
No data -> the script says so and exits; it never invents numbers.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss

from vpredict import config
from vpredict.data import store
from vpredict.evaluation.tiers import TIER_ORDER, classify_tier
from vpredict.evaluation.collinearity import top_correlations, vif_table
from vpredict.features.build import augment_swapped, build_features, chronological_split
from vpredict.modeling import series as sr
from vpredict.modeling.baselines import (compute_prematch_elo, elo_row_probs,
                                         matches_lite_from_maps, tune_elo_k)
from vpredict.modeling.train import (PlattCalibrator, ll,
                                     predict_calibrated, select_model)
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

EPS = 1e-6


def _clip(p):
    return np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)


def _brier(y, p) -> float:
    return float(brier_score_loss(y, _clip(p)))


def _ece(y, p, n_bins: int = 10) -> float:
    bins = pd.qcut(p, q=n_bins, duplicates="drop")
    g = pd.DataFrame({"y": y, "p": p, "bin": bins}).groupby("bin", observed=True)
    w = g.size() / len(p)
    return float((w * (g["p"].mean() - g["y"].mean()).abs()).sum())


def _elo_p(pair) -> float:
    ra, rb = pair
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / config.ELO_SCALE))


def calibration_points(y, p, n_bins=10):
    bins = pd.qcut(p, q=min(n_bins, max(3, len(p) // 40)), duplicates="drop")
    g = pd.DataFrame({"y": y, "p": p, "bin": bins}).groupby("bin", observed=True)
    return g["p"].mean().to_numpy(), g["y"].mean().to_numpy()


def plot_calibration(panels, path, watermark: bool):
    fig, axes = plt.subplots(1, len(panels), figsize=(6 * len(panels), 5.4))
    axes = np.atleast_1d(axes)
    for ax, (title, curves) in zip(axes, panels):
        ax.plot([0, 1], [0, 1], "--", color="#999", lw=1, label="perfect")
        for label, y, p, color in curves:
            mx, my = calibration_points(y, p)
            ax.plot(mx, my, "o-", color=color, label=label, ms=4)
        ax.set_xlabel("predicted P(team A wins)")
        ax.set_ylabel("observed frequency")
        ax.set_title(title)
        ax.legend()
        if watermark:
            ax.text(0.5, 0.5, "SYNTHETIC DEMO DATA", transform=ax.transAxes,
                    fontsize=24, color="red", alpha=0.25, ha="center",
                    va="center", rotation=30)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fmt(v) -> str:
    return "\u2014" if v is None else f"{v:.4f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(config.MATCHES_JSONL))
    ap.add_argument("--reports", default=str(config.REPORTS_DIR))
    ap.add_argument("--half-life", type=float, default=config.DEFAULT_HALF_LIFE_DAYS)
    ap.add_argument("--roster-factor", type=float, default=config.DEFAULT_ROSTER_FACTOR)
    ap.add_argument("--features-cache", default=None,
                    help="joblib path for the built FeatureSet: load if it "
                         "exists, else build and save. Same numbers either "
                         "way; skips the expensive as-of rebuild on re-runs.")
    ap.add_argument("--spot-checks", type=int, default=None,
                    help="override the runtime leakage spot-check count")
    args = ap.parse_args()

    matches = store.load_matches(args.data)
    maps_df = store.maps_frame(matches)
    if maps_df.empty:
        print("No completed matches found at", args.data)
        print("Nothing to evaluate \u2014 this project never invents numbers.")
        print("Run the crawler for real data or `make demo` for a watermarked synthetic run.")
        return 1

    synthetic = bool(maps_df["synthetic"].any())
    banner = "SYNTHETIC DEMO DATA \u2014 NOT REAL RESULTS" if synthetic else ""
    if banner:
        print("=" * 66 + f"\n  {banner}\n" + "=" * 66)

    # ---------------------------------------------------------------- features & split
    cache = Path(args.features_cache) if args.features_cache else None
    if cache and cache.exists():
        import joblib
        fs = joblib.load(cache)
        print(f"loaded cached FeatureSet from {cache}")
    else:
        kw = {} if args.spot_checks is None else {"spot_checks": args.spot_checks}
        fs = build_features(maps_df, half_life_days=args.half_life,
                            roster_factor=args.roster_factor, **kw)
        if cache:
            import joblib
            joblib.dump(fs, cache)
            print(f"cached FeatureSet -> {cache}")
    splits = chronological_split(fs.meta)
    tr, va, te = splits["train"], splits["val"], splits["test"]
    y = fs.y.to_numpy()
    if va.sum() < 30 or te.sum() < 30:
        print(f"Not enough data to evaluate honestly (val={int(va.sum())}, "
              f"test={int(te.sum())} map rows). Scrape a longer window.")
        return 1

    veto_by_match = {m.match_id: m.veto_raw for m in matches}
    known_maps = sorted(maps_df["map_name"].unique())

    # Per-match series geometry (played order + veto-completed tail).
    seqs: dict[str, sr.SeriesMaps] = {}
    played_by_match: dict[str, list[str]] = {}
    for mid, g in fs.meta.groupby("match_id", sort=False):
        played = g.sort_values("map_index")["map_name"].tolist()
        played_by_match[mid] = played
        best_of = int(g["best_of"].iloc[0])
        seqs[mid] = sr.complete_sequence(played, veto_by_match.get(mid, ""),
                                         best_of, known_maps)
    extra = {mid: [m for m in s.maps[len(played_by_match[mid]):] if m]
             for mid, s in seqs.items()}

    # ---------------------------------------------------------------- baselines
    lites = matches_lite_from_maps(maps_df, extra_maps=extra)
    best_k, p_elo, k_table = tune_elo_k(lites, fs.meta, y, va)
    k_edge = best_k == max(config.ELO_K_GRID)
    elo_best = compute_prematch_elo(lites, k=best_k)      # baseline (tuned K)
    elo_feat = compute_prematch_elo(lites, k=config.DEFAULT_ELO_K)  # feature K
    p_elo_me = np.array([_elo_p(elo_best[r.match_id]["maps"][r.map_name])
                         for r in fs.meta.itertuples()])

    # ---------------------------------------------------------------- main model
    n_train_matches = int(fs.meta.loc[tr, "match_id"].nunique())
    X_tr, y_tr = augment_swapped(fs.X[tr], fs.y[tr])
    sel = select_model(X_tr, y_tr, fs.X[va], y[va], n_train_matches)
    p_model = predict_calibrated(sel, fs.X)

    # ================================================================ 1. map level
    rows_map = [
        (f"model: {sel['name']} + {sel['cal_name']}",
         ll(y[te], p_model[te]), _brier(y[te], p_model[te]),
         accuracy_score(y[te], p_model[te] >= 0.5)),
        (f"elo baseline (K={best_k:g}, tuned on val)",
         ll(y[te], p_elo[te]), _brier(y[te], p_elo[te]),
         accuracy_score(y[te], p_elo[te] >= 0.5)),
        (f"elo (map-effective blend, K={best_k:g})",
         ll(y[te], p_elo_me[te]), _brier(y[te], p_elo_me[te]),
         accuracy_score(y[te], p_elo_me[te] >= 0.5)),
        ("favourite (higher pre-match Elo)", None, None,
         accuracy_score(y[te], p_elo[te] >= 0.5)),
        ("constant 0.5", ll(y[te], np.full(int(te.sum()), 0.5)),
         _brier(y[te], np.full(int(te.sum()), 0.5)), None),
    ]

    # ================================================================ 2. match level
    meta = fs.meta.copy()
    meta["tier"] = meta["event"].map(classify_tier)
    test_mids = meta.loc[te, "match_id"].unique().tolist()
    val_mids = meta.loc[va, "match_id"].unique().tolist()
    sweep_mids = val_mids + test_mids
    test_set = set(test_mids)

    # Decider feature rows (veto-known, never played) for every val AND test
    # series, built once; each candidate model scores them in one batch.
    dummy_cols = [c for c in fs.feature_names
                  if c.startswith("map_") and c != "map_elo_diff"]
    decider_rows, decider_key = [], []
    for mid in sweep_mids:
        s = seqs[mid]
        played_n = len(played_by_match[mid])
        for name in s.maps[played_n:]:
            if name is None:
                continue
            i = meta.index[meta["match_id"] == mid][0]
            row = fs.X.loc[i].copy()
            for c in dummy_cols:
                row[c] = 0.0
            if f"map_{name}" in dummy_cols:
                row[f"map_{name}"] = 1.0
            pair = elo_feat[mid]["maps"].get(name)
            if pair is not None:
                row["map_elo_diff"] = pair[0] - pair[1]
            decider_rows.append(row)
            decider_key.append((mid, name))
    Xd = pd.DataFrame(decider_rows)[fs.feature_names] if decider_rows else None

    # Model-independent per-series caches: label, row positions, Elo DP prob.
    row_pos, labels, pe_series, fav_series, tier_of = {}, {}, {}, {}, {}
    n_veto = n_fallback = n_full = 0
    for mid in sweep_mids:
        g = meta[meta["match_id"] == mid].sort_values("map_index")
        idx = g.index.to_numpy()
        row_pos[mid] = meta.index.get_indexer(idx)
        best_of = int(g["best_of"].iloc[0])
        labels[mid] = int(int(fs.y.loc[idx].sum()) == best_of // 2 + 1)
        tier_of[mid] = g["tier"].iloc[0]
        fav_series[mid] = int(elo_best[mid]["p_a"] >= 0.5)
        s = seqs[mid]
        pe_played = [_elo_p(elo_best[mid]["maps"][n]) for n in played_by_match[mid]]
        probs_e = []
        for j, name in enumerate(s.maps):
            if j < len(pe_played):
                probs_e.append(pe_played[j])
            elif name is not None and elo_best[mid]["maps"].get(name):
                probs_e.append(_elo_p(elo_best[mid]["maps"][name]))
            else:
                probs_e.append(float(np.mean(pe_played)))
        pe_series[mid] = sr.series_prob(probs_e)
        if mid in test_set:      # provenance is a test-window statistic
            if s.n_fallback:
                n_fallback += 1
            elif s.n_filled_from_veto:
                n_veto += 1
            else:
                n_full += 1

    def model_series(mids: list, p_all: np.ndarray, p_dec: dict) -> np.ndarray:
        """Series DP per match for any per-row probability vector."""
        out = []
        for mid in mids:
            pm_played = list(p_all[row_pos[mid]])
            probs = []
            for j, name in enumerate(seqs[mid].maps):
                if j < len(pm_played):
                    probs.append(pm_played[j])
                elif name is not None and (mid, name) in p_dec:
                    probs.append(p_dec[(mid, name)])
                else:
                    probs.append(float(np.mean(pm_played)))
            out.append(sr.series_prob(probs))
        return np.array(out)

    p_decider: dict[tuple, float] = {}
    if Xd is not None:
        p_decider = dict(zip(decider_key, predict_calibrated(sel, Xd)))
    m_y = np.array([labels[m] for m in test_mids])
    m_pm = model_series(test_mids, p_model, p_decider)
    m_pe = np.array([pe_series[m] for m in test_mids])
    m_fav = [fav_series[m] for m in test_mids]
    m_tier = [tier_of[m] for m in test_mids]
    rows_match = [
        ("model (per-map probs \u2192 series DP)",
         ll(m_y, m_pm), _brier(m_y, m_pm), accuracy_score(m_y, m_pm >= 0.5)),
        (f"elo baseline (map-effective, K={best_k:g}, series DP)",
         ll(m_y, m_pe), _brier(m_y, m_pe), accuracy_score(m_y, m_pe >= 0.5)),
        ("favourite (higher pre-match Elo)", None, None,
         accuracy_score(m_y, np.array(m_fav))),
        ("constant 0.5", ll(m_y, np.full(len(m_y), 0.5)),
         _brier(m_y, np.full(len(m_y), 0.5)), None),
    ]

    # ================================================================ 3. by tier
    tier_counts_all = meta.drop_duplicates("match_id")["tier"].value_counts()
    tier_rows = []
    for tier in TIER_ORDER:
        mask = (te & (meta["tier"] == tier).to_numpy())
        n = int(mask.sum())
        if n == 0:
            tier_rows.append((tier, 0, None, None, None, None))
            continue
        tier_rows.append((tier, n,
                          ll(y[mask], p_model[mask]),
                          accuracy_score(y[mask], p_model[mask] >= 0.5),
                          ll(y[mask], p_elo[mask]),
                          accuracy_score(y[mask], p_elo[mask] >= 0.5)))

    # ================================================================ 4. tier-1 restriction
    t1 = (meta["tier"] == "tier1").to_numpy()
    exp_rows, exp_note, exp_design = [], "", ""
    n_t1_train = int(meta.loc[tr & t1, "match_id"].nunique())
    n_t1_val = int(meta.loc[va & t1, "match_id"].nunique())
    if n_t1_train < 40:
        exp_note = (f"insufficient tier-1 training matches ({n_t1_train}) "
                    "\u2014 experiment skipped")
    else:
        exp_design = (
            f"Design: the tier-1 arm restricts TRAINING rows only ({n_t1_train} "
            "tier-1 train matches). Selection and calibration use the FULL "
            "validation window for both arms, which isolates the training-set "
            f"effect \u2014 and is forced anyway: the val window contains "
            f"{n_t1_val} tier-1 matches (a VCT calendar gap between stages). "
            "History/features always use ALL matches; test rows are identical "
            "across arms.")
        arms = {"train on ALL tiers": sel}
        X1, y1 = augment_swapped(fs.X[tr & t1], fs.y[tr & t1])
        sel_t1 = select_model(X1, y1, fs.X[va], y[va], n_t1_train)
        arms["train on TIER-1 only"] = sel_t1
        for arm_name, arm in arms.items():
            p = predict_calibrated(arm, fs.X)
            for slice_name, mask in (("all test rows", te),
                                     ("tier-1 test rows", te & t1)):
                if mask.sum() == 0:
                    continue
                exp_rows.append((arm_name, arm["name"], slice_name, int(mask.sum()),
                                 ll(y[mask], p[mask]),
                                 accuracy_score(y[mask], p[mask] >= 0.5)))

    # ================================================================ 6. series-grain C sweep
    # Authorized tuning: map-grain selection chose maximal shrinkage, but the
    # deliverable is the series. Refit LR per C, recalibrate on validation,
    # SELECT by validation series log loss, and report test at both grains
    # for every candidate so nothing is cherry-picked.
    y_val_series = np.array([labels[m] for m in val_mids])
    sweep_rows, best_sweep = [], None
    for C in (0.03, 0.1, 0.3, 1.0, 3.0):
        pipe = make_pipeline(StandardScaler(),
                             LogisticRegression(C=C, max_iter=4000))
        pipe.fit(X_tr, y_tr)
        cal = PlattCalibrator().fit(pipe.predict_proba(fs.X[va])[:, 1], y[va])
        p_all = cal.transform(pipe.predict_proba(fs.X)[:, 1])
        p_dec = (dict(zip(decider_key,
                          cal.transform(pipe.predict_proba(Xd)[:, 1])))
                 if Xd is not None else {})
        v_ll = ll(y_val_series, model_series(val_mids, p_all, p_dec))
        t_series = model_series(test_mids, p_all, p_dec)
        rec = (C, v_ll,
               ll(y[te], p_all[te]),
               accuracy_score(y[te], p_all[te] >= 0.5),
               ll(m_y, t_series), _brier(m_y, t_series),
               accuracy_score(m_y, t_series >= 0.5))
        sweep_rows.append(rec)
        if best_sweep is None or v_ll < best_sweep[1]:
            best_sweep = rec
    v_ll_incumbent = ll(y_val_series, model_series(val_mids, p_model, p_decider))

    # ================================================================ report
    n_matches = int(meta["match_id"].nunique())
    reports = Path(args.reports)
    reports.mkdir(parents=True, exist_ok=True)
    # Collinearity (spec non-negotiable): training rows, continuous/context
    # features only (map one-hots excluded). Full table -> collinearity.csv.
    cont_cols = [c for c in fs.feature_names
                 if not (c.startswith("map_") and c != "map_elo_diff")]
    vif = vif_table(fs.X.loc[tr, cont_cols])
    corr_pairs = top_correlations(fs.X.loc[tr, cont_cols], k=6)
    vif.to_csv(reports / "collinearity.csv", index=False)
    cal_png = reports / "calibration.png"
    plot_calibration(
        [("Map level \u2014 test window",
          [("model", y[te], p_model[te], "#1f6f8b"),
           ("elo", y[te], p_elo[te], "#c05746")]),
         ("Match level (series) \u2014 test window",
          [("model", m_y, m_pm, "#1f6f8b"),
           ("elo", m_y, m_pe, "#c05746")])],
        cal_png, synthetic)

    b = splits["boundaries"]
    L = []
    L += ["# Results" + (f" \u2014 {banner}" if banner else ""), "",
          f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} by "
          "`scripts/evaluate.py` (the only source of the numbers below).", ""]
    L += [f"- Matches: {n_matches} usable ({len(fs.X)} map rows) from "
          f"{meta['start_ts'].min():%Y-%m-%d} to {meta['start_ts'].max():%Y-%m-%d}",
          f"- Split by match, chronological: train/val/test = "
          f"{b['n_matches']['train']}/{b['n_matches']['val']}/{b['n_matches']['test']} "
          f"(train ends {b['train_end']:%Y-%m-%d}, val ends {b['val_end']:%Y-%m-%d})",
          f"- Gate: {sel['gate_note']}; selected by validation log loss",
          f"- Feature params: half_life={args.half_life}d, roster_factor={args.roster_factor}, "
          f"feature Elo K={config.DEFAULT_ELO_K}",
          f"- Tier B columns dropped: {fs.dropped_tier_b or 'none'}",
          "- Elo K grid (val log loss): " +
          ", ".join(f"{k:g}: {v:.4f}" for k, v in k_table) +
          ("  \u2190 best K at grid edge" if k_edge else ""), ""]

    L += ["## 1. Map level (test window)", "",
          "| model | log loss | brier | accuracy |", "|---|---|---|---|"]
    L += [f"| {n} | {fmt(a)} | {fmt(bb)} | {fmt(c)} |" for n, a, bb, c in rows_map]
    L += ["", f"- ECE (model, 10 quantile bins): {_ece(y[te], p_model[te]):.4f}", ""]

    L += ["## 2. Match level \u2014 series probabilities (test window)", "",
          f"{len(m_y)} test matches. Per-map probabilities aggregated by exact "
          "best-of DP over the post-veto map set.",
          f"Map-set provenance: {n_full} series played all maps, {n_veto} "
          f"completed from the veto note, {n_fallback} needed the mean-prob "
          "fallback (veto missing/unparseable).", "",
          "| model | log loss | brier | accuracy |", "|---|---|---|---|"]
    L += [f"| {n} | {fmt(a)} | {fmt(bb)} | {fmt(c)} |" for n, a, bb, c in rows_match]
    L += ["", f"- ECE (model, 6 quantile bins): {_ece(m_y, m_pm, 6):.4f}", ""]

    L += ["## 3. By event tier (map level, test window)", "",
          "Tier mapping (all usable matches): " +
          ", ".join(f"{t}={int(tier_counts_all.get(t, 0))}" for t in TIER_ORDER), "",
          "| tier | test map rows | model LL | model acc | elo LL | elo acc |",
          "|---|---|---|---|---|---|"]
    for t, n, mll, macc, ell_, eacc in tier_rows:
        L += [f"| {t} | {n} | {fmt(mll)} | {fmt(macc)} | {fmt(ell_)} | {fmt(eacc)} |"]
    L += [""]

    L += ["## 4. Tier-1-restricted training (map level)", ""]
    if exp_note:
        L += [exp_note, ""]
    else:
        L += [exp_design, "",
              "| training rows | selected | eval slice | n rows | log loss | accuracy |",
              "|---|---|---|---|---|---|"]
        L += [f"| {a} | {mn} | {s} | {n} | {fmt(l)} | {fmt(ac)} |"
              for a, mn, s, n, l, ac in exp_rows]
        L += [""]
    L += ["## 5. Collinearity (training rows)", "",
          "VIF over the continuous/context features (map one-hots excluded); "
          "full table in `collinearity.csv`. High VIF is expected here and "
          "does not hurt regularized prediction, but it means individual "
          "coefficients must not be read as marginal effects.", "",
          "| feature | VIF |", "|---|---|"]
    L += [f"| {r.feature} | {r.vif:.2f} |" for r in vif.itertuples()]
    high = vif.loc[vif["vif"] > 10, "feature"].tolist()
    if high:
        L += ["", "- VIF > 10 (severe): " + ", ".join(high)]
    else:
        L += ["", "- No feature exceeds the conventional VIF > 10 threshold."]
    L += ["- Largest |correlations|: " +
          "; ".join(f"{a} ~ {b}: {v:+.2f}" for a, b, v in corr_pairs), ""]

    L += ["## 6. Series-grain C sweep (authorized tuning)", "",
          "LR refit per C on the same augmented training rows, "
          "Platt-recalibrated on validation. Selection column: validation "
          "SERIES log loss (the deliverable grain). Test columns are shown "
          "for every candidate so nothing is cherry-picked.", "",
          "| C | val series LL (selector) | test map LL | test map acc "
          "| test series LL | test series Brier | test series acc |",
          "|---|---|---|---|---|---|---|"]
    for C, vll_, tml, tma, tsl, tsb, tsa in sweep_rows:
        star = " \u2605" if best_sweep and C == best_sweep[0] else ""
        L += [f"| {C:g}{star} | {vll_:.4f} | {tml:.4f} | {tma:.4f} "
              f"| {tsl:.4f} | {tsb:.4f} | {tsa:.4f} |"]
    L += ["", f"- \u2605 = selected by validation series log loss "
          f"(C={best_sweep[0]:g}).",
          f"- Incumbent ({sel['name']} + {sel['cal_name']}): "
          f"val series LL {v_ll_incumbent:.4f}.",
          f"- Elo reference on the same test series: LL {ll(m_y, m_pe):.4f}, "
          f"Brier {_brier(m_y, m_pe):.4f}, "
          f"acc {accuracy_score(m_y, m_pe >= 0.5):.4f}.", ""]
    L += [f"- Calibration curves (both grains): `{cal_png.name}`", ""]
    if synthetic:
        L += ["**Every number above comes from a seeded simulator. It proves the",
              "pipeline runs end to end; it says nothing about real Valorant.**", ""]
    (reports / "results.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\nwrote {reports/'results.md'} and {cal_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
