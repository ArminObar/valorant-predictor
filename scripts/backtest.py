#!/usr/bin/env python3
"""Run the walk-forward backtest ONCE and publish the result.

    python scripts/backtest.py --features-cache data/processed/features_cache.parquet
    python scripts/backtest.py ... --push          # also POST to the site
    python scripts/backtest.py ... --replace       # ONLY after a model change

Outputs:
  data/processed/backtest.json            the served summary (per-tier only)
  data/reports/backtest_rows_<stamp>.jsonl  full per-match audit record
  data/reports/backtest_<stamp>.json      immutable dated copy of the summary

Run-once discipline (spec item 7): if data/processed/backtest.json already
exists, the script REFUSES to run. `--replace` lifts that only when the
currently shipped bundle's version differs from the one recorded in the
existing file — the mechanical form of "re-run only when the model
changes, never to tune against the result" — and archives the old summary
under its stamp before writing the new one. The old result stays.

Market columns: if the local odds log has captures linking to backtest
matches, a BACKTEST-labeled market join is included (simulated model
probability vs the real captured price). Coverage grows as odds accumulate;
it is near-empty on the first run and that is stated rather than padded.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from vpredict import config
from vpredict.data import store
from vpredict.evaluation.backtest import run_backtest
from vpredict.features.build import FeatureSet

BACKTEST_JSON = config.PROCESSED_DIR / "backtest.json"


def replace_gate(existing: dict | None, shipped: str | None,
                 replace: bool) -> tuple[bool, str]:
    """Run-once enforcement, mechanically. Returns (allowed, message).
    No existing result -> allowed. Existing result -> refused unless
    --replace AND the shipped bundle version changed since the recorded
    run — re-running against the same model would be tuning against it."""
    if existing is None:
        return True, "first run"
    if not replace:
        return False, ("result exists (run-once). It stands; re-run with "
                       "--replace only after a model change.")
    old_shipped = existing.get("live_bundle_version")
    if shipped is not None and shipped == old_shipped:
        return False, (f"--replace refused: shipped bundle version is "
                       f"unchanged ({shipped}).")
    return True, f"model changed ({old_shipped} -> {shipped})"


def _shipped_bundle_version() -> str | None:
    try:
        from vpredict.modeling.train import load_bundle
        return load_bundle().get("version")
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--features-cache", default=None,
                    help="joblib FeatureSet built with the default feature "
                         "params; loaded if present, else built and saved")
    ap.add_argument("--warmup-matches", type=int, default=300)
    ap.add_argument("--replace", action="store_true",
                    help="allowed ONLY when the shipped bundle version "
                         "differs from the recorded one (model changed)")
    ap.add_argument("--push", action="store_true",
                    help="POST the summary to the live site's ingest "
                         "endpoint (needs VPREDICT_INGEST_TOKEN)")
    ap.add_argument("--push-only", action="store_true",
                    help="POST the EXISTING result without recomputing "
                         "anything (run-once stays intact)")
    ap.add_argument("--rebuild-report", action="store_true",
                    help="regenerate the summary's metric blocks from the "
                         "newest frozen rows file — report-format changes "
                         "never require a re-walk; no prediction is "
                         "recomputed")
    ap.add_argument("--rows", default=None,
                    help="rows file for --rebuild-report (default: the one "
                         "the existing summary names)")
    ap.add_argument("--base-url",
                    default=config.ODDS_UPCOMING_URL.rsplit("/api/", 1)[0])
    args = ap.parse_args()

    shipped = _shipped_bundle_version()
    existing = (json.loads(BACKTEST_JSON.read_text(encoding="utf-8"))
                if BACKTEST_JSON.exists() else None)
    if args.push_only:
        if existing is None:
            print(f"nothing to push: {BACKTEST_JSON} does not exist")
            return 2
        return _push(existing, args.base_url)
    if args.rebuild_report:
        if existing is None:
            print("nothing to rebuild: no existing summary")
            return 2
        from vpredict.evaluation.backtest import rebuild_report
        rf = Path(args.rows) if args.rows else (
            config.REPORTS_DIR / existing["rows_file"])
        if not rf.exists():
            print(f"rows file not found: {rf}")
            return 2
        with gzip.open(rf, "rt", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f]
        report = rebuild_report(rows, existing, rf.name)
        tmp = BACKTEST_JSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
        tmp.replace(BACKTEST_JSON)
        print(f"summary rebuilt from {rf.name} ({len(rows)} rows) -> "
              f"{BACKTEST_JSON}")
        for tier, pers in report["per_tier_by_period"].items():
            for per, m in pers.items():
                print(f"  {tier:14s} {per}  n={m['n_scored']:4d}  "
                      f"model {m['model_ll']:.4f}/{m['model_acc']:.3f}  "
                      f"elo {m['elo_ll']:.4f}/{m['elo_acc']:.3f}")
        return 0
    allowed, msg = replace_gate(existing, shipped, args.replace)
    if not allowed:
        print(f"REFUSING: {msg}")
        return 2
    if existing is not None:
        stamp = (existing.get("generated_at", "unknown")
                 .replace(":", "").replace("-", "")[:15])
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        archive = config.REPORTS_DIR / f"backtest_{stamp}.json"
        if not archive.exists():
            archive.write_text(json.dumps(existing, indent=1),
                               encoding="utf-8")
        print(f"{msg}; previous result archived to {archive}")

    print("loading store...")
    maps_df = store.maps_frame(store.iter_matches(config.MATCHES_JSONL))
    features = None
    cache = Path(args.features_cache) if args.features_cache else None
    if cache and cache.exists():
        features = FeatureSet.load(cache)
        print(f"loaded feature cache {cache}")

    t0 = time.perf_counter()
    report, rows = run_backtest(
        maps_df, features=features, warmup_matches=args.warmup_matches,
        progress=lambda n: print(f"  ...{n} predictions", flush=True))
    report["live_bundle_version"] = shipped
    report["runtime_s"] = round(time.perf_counter() - t0, 1)

    # Market join over the local odds log, BACKTEST-labeled. The join reads
    # ledger-shaped rows; the simulated rows carry the same keys.
    odds_note = "no odds log on this machine"
    if config.ODDS_JSONL.exists():
        from vpredict.odds.markets import build_markets_report
        from vpredict.odds.schema import iter_captures
        shaped = [{**r, "p_maps_dist": json.dumps(r["maps_dist"])}
                  for r in rows]
        mk = build_markets_report(shaped, list(iter_captures()),
                                  section="BACKTEST")
        report["markets"] = mk
        odds_note = (f"{mk['summary']['n_covered']} market-covered "
                     f"simulated picks")
    else:
        report["markets"] = None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    rows_path = config.REPORTS_DIR / f"backtest_rows_{stamp}.jsonl.gz"
    with gzip.open(rows_path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    report["rows_file"] = rows_path.name

    BACKTEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = BACKTEST_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    tmp.replace(BACKTEST_JSON)
    dated = config.REPORTS_DIR / f"backtest_{stamp}.json"
    dated.write_text(json.dumps(report, indent=1), encoding="utf-8")

    w = report["window"]
    print(f"\nBACKTEST done in {report['runtime_s']}s: "
          f"{w['n_predictions']} predictions, {w['n_retrains']} retrains, "
          f"{odds_note}")
    for tier, m in report["per_tier"].items():
        if m.get("n_scored"):
            print(f"  {tier:14s} n={m['n_scored']:4d}  "
                  f"model {m['model_ll']:.4f}/{m['model_acc']:.3f}  "
                  f"elo {m['elo_ll']:.4f}/{m['elo_acc']:.3f}")
    print(f"summary -> {BACKTEST_JSON}\nrows    -> {rows_path}\n"
          f"dated   -> {dated}")

    if args.push:
        return _push(report, args.base_url)
    return 0


def _push(report: dict, base_url: str) -> int:
    token = os.environ.get("VPREDICT_INGEST_TOKEN")
    if not token:
        print("VPREDICT_INGEST_TOKEN not set — not pushed.")
        return 1
    import requests
    r = requests.post(f"{base_url}/api/ingest/backtest", json=report,
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=60)
    print(f"push: HTTP {r.status_code}")
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
