#!/usr/bin/env python3
"""Build the markets/EV report and publish it to the live site.

    python scripts/publish_markets.py                    # build + POST
    python scripts/publish_markets.py --no-push          # build only
    python scripts/publish_markets.py --ledger data/serving/ledger.sqlite

The odds log lives on this machine (capture never runs on Render), while
the frozen ledger lives behind the live API — so the join happens HERE:
ledger rows are read from /api/scoreboard (graded + pending), captures from
the local append-only log, and the derived report is written to
data/processed/markets.json and POSTed to the site's ingest endpoint.

The report is a derived VIEW — safe to overwrite on every run. The two
sources of truth stay append-only where they live: the ledger on Render's
disk, the odds log here.

Pushing requires VPREDICT_INGEST_TOKEN in the environment, matching the
same variable on the Render service. Add this to the same cron as the
capture, after it:

    python scripts/capture_odds.py --once && python scripts/publish_markets.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from vpredict import config
from vpredict.odds.markets import build_markets_report
from vpredict.odds.schema import iter_captures


def ledger_rows_from_api(base_url: str) -> list[dict]:
    import requests
    r = requests.get(f"{base_url}/api/scoreboard", timeout=20)
    r.raise_for_status()
    d = r.json()
    return list(d.get("graded", [])) + list(d.get("pending", []))


def ledger_rows_from_sqlite(path: str) -> list[dict]:
    from vpredict.serving.ledger import Ledger
    led = Ledger(path)
    try:
        return led.rows(graded=True, limit=100000) + \
            led.rows(graded=False, limit=100000)
    finally:
        led.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url",
                    default=config.ODDS_UPCOMING_URL.rsplit("/api/", 1)[0],
                    help="live site base URL (ledger source and push target)")
    ap.add_argument("--ledger", default=None,
                    help="read ledger rows from a local sqlite file instead "
                         "of the live API (dev only — the public record is "
                         "the one behind the API)")
    ap.add_argument("--no-push", action="store_true",
                    help="write data/processed/markets.json, skip the POST")
    args = ap.parse_args()

    rows = (ledger_rows_from_sqlite(args.ledger) if args.ledger
            else ledger_rows_from_api(args.base_url))
    captures = list(iter_captures())
    report = build_markets_report(rows, captures)

    config.MARKETS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.MARKETS_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    tmp.replace(config.MARKETS_JSON)
    s = report["summary"]
    print(f"markets report: {s['n_covered']} covered picks "
          f"({s['n_graded']} graded, {report['gate']['n_graded']}/"
          f"{report['gate']['required']} toward the EV gate) -> "
          f"{config.MARKETS_JSON}")

    if args.no_push:
        return 0
    token = os.environ.get("VPREDICT_INGEST_TOKEN")
    if not token:
        print("VPREDICT_INGEST_TOKEN not set — built locally, not pushed. "
              "Set the same token here and on Render to publish.")
        return 1
    import requests
    r = requests.post(f"{args.base_url}/api/ingest/markets",
                      json=report,
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=30)
    if r.status_code == 200:
        print(f"pushed to {args.base_url}/api/ingest/markets")
        return 0
    print(f"push failed: HTTP {r.status_code} — {r.text[:200]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
