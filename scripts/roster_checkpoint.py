#!/usr/bin/env python3
"""Roster-continuity live checkpoint (ASSUMPTIONS §70).

Run anytime in the Render Shell:  python3 scripts/roster_checkpoint.py
The tool gates itself: accumulation status only below n=30, DIRECTIONAL
numbers with no verdict at 30-49, the pinned decision read at n>=50.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vpredict import config                                  # noqa: E402
from vpredict.serving.ledger import Ledger                   # noqa: E402
from vpredict.serving.roster_checkpoint import checkpoint, render  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(config.DATA_DIR))
    ap.add_argument("--since", default=None,
                    help="override the era boundary (ISO ts; default "
                         "config.ROSTER_LIVE_SINCE)")
    args = ap.parse_args()
    led = Ledger(Path(args.data) / "serving" / "ledger.sqlite")
    try:
        rows = led.rows(graded=True, limit=100000)
    finally:
        led.close()
    print(render(checkpoint(rows, since=args.since)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
