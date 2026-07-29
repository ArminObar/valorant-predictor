#!/usr/bin/env python3
"""Capture odds for the frozen predictions — cron-friendly.

    python scripts/capture_odds.py --once --sources pinnacle --push
    python scripts/capture_odds.py --once --sources cloudbet        # local dev
    python scripts/capture_odds.py --push-log                       # one-time migration

Implementation lives in vpredict.odds.capture (shared with the server
refresh cycle, which runs the Cloudbet leg itself — ASSUMPTIONS §42).
This CLI is the Mac home of the Pinnacle leg: capture locally, then
--push the new records to the server's validated, deduping odds ingest
so the server-side markets build sees both books. --push-log pushes the
entire local log once, seeding the server with capture history.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from vpredict.odds.capture import (acquire_capture_lock,  # noqa: F401 (re-exports:
                                   decide_kind, load_predictions,  # tests and
                                   push_captures, run_once)        # old cron refs)
from vpredict.odds.schema import iter_captures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="one capture pass")
    ap.add_argument("--sources", default="cloudbet,pinnacle",
                    help="comma list: cloudbet,pinnacle")
    ap.add_argument("--from-file", default=None)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--push", action="store_true",
                    help="POST this pass's appended records to the server")
    ap.add_argument("--push-log", action="store_true",
                    help="POST the ENTIRE local log (idempotent seed)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s %(message)s")

    if args.push_log:
        records = list(iter_captures())
        print(json.dumps(push_captures(records), indent=1))
        return 0
    if not args.once:
        print("nothing to do: pass --once (or --push-log)")
        return 1
    lock = acquire_capture_lock()
    if lock is None:
        print("another capture is running; skipping this fire")
        return 0
    try:
        report, appended = run_once(
            [x.strip() for x in args.sources.split(",") if x.strip()],
            from_file=args.from_file, debug=args.debug)
        if args.push and appended:
            report["push"] = push_captures(appended)
        print(json.dumps(report, indent=1))
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
