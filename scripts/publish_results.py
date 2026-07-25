#!/usr/bin/env python3
"""Publish the recent-window evaluation summary to the live site.

    python scripts/publish_results.py              # validate + copy + POST
    python scripts/publish_results.py --no-push    # validate + copy only

Reads the machine-readable summary that scripts/evaluate.py writes next
to results.md (data/reports/results_summary.json by default), refuses
anything watermarked synthetic or structurally incomplete, copies it to
data/processed/results_summary.json (what GET /api/results serves when
self-hosting), and POSTs it to the live site's ingest endpoint — the
same Bearer-token pattern as publish_markets.py and backtest --push.

This script never computes or edits a metric; it only moves the
artifact. Every number the site displays therefore traces to exactly one
scripts/evaluate.py run. Pushing requires VPREDICT_INGEST_TOKEN in the
environment, matching the same variable on the Render service (already
configured if publish_markets.py works).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from vpredict import config
from vpredict.evaluation.results_summary import validate_summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--summary",
                    default=str(config.REPORTS_DIR / "results_summary.json"),
                    help="summary written by scripts/evaluate.py")
    ap.add_argument("--base-url",
                    default=config.ODDS_UPCOMING_URL.rsplit("/api/", 1)[0],
                    help="live site base URL (push target)")
    ap.add_argument("--no-push", action="store_true",
                    help="copy to data/processed/, skip the POST")
    args = ap.parse_args()

    path = Path(args.summary)
    if not path.exists():
        print(f"no summary at {path} — run scripts/evaluate.py first "
              "(it writes results_summary.json next to results.md).")
        return 1
    report = json.loads(path.read_text(encoding="utf-8"))
    problems = validate_summary(report)
    if problems:
        print("refusing to publish:")
        for p in problems:
            print(f"  - {p}")
        return 1

    out = config.PROCESSED_DIR / "results_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    tmp.replace(out)
    s, m = report["series"], report["map"]
    print(f"results summary: series LL {s['model']['log_loss']:.4f} vs elo "
          f"{s['elo']['log_loss']:.4f} over {s['n']} series; map LL "
          f"{m['model']['log_loss']:.4f} vs {m['elo']['log_loss']:.4f} "
          f"over {m['n_rows']} rows -> {out}")

    if args.no_push:
        return 0
    token = os.environ.get("VPREDICT_INGEST_TOKEN")
    if not token:
        print("VPREDICT_INGEST_TOKEN not set — built locally, not pushed. "
              "Set the same token here and on Render to publish.")
        return 1
    import requests
    r = requests.post(f"{args.base_url}/api/ingest/results", json=report,
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=30)
    if r.status_code == 200:
        print(f"pushed to {args.base_url}/api/ingest/results")
        return 0
    print(f"push failed: HTTP {r.status_code} — {r.text[:200]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
