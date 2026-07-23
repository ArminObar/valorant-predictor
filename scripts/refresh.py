#!/usr/bin/env python3
"""One full refresh cycle (crawl -> grade -> retrain if stale -> predict).
Cron this on any box with its own disk; on Render/Railway prefer the
in-process scheduler (VPREDICT_REFRESH=1) because disks are per-service."""
import argparse
import json
import logging

from vpredict.serving.refresh import refresh_cycle


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-crawl", action="store_true",
                    help="skip network steps (grade + retrain + predict from disk)")
    args = ap.parse_args()
    print(json.dumps(refresh_cycle(crawl=not args.no_crawl), indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
