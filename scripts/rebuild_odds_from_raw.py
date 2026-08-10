#!/usr/bin/env python3
"""Rebuild the odds log's lost head from /data/raw (ASSUMPTIONS §67).

Dry run (default):  python3 scripts/rebuild_odds_from_raw.py
Apply:              python3 scripts/rebuild_odds_from_raw.py --apply

Reads the raw response archive, replays it through the current parser,
linker, kind logic, and priceable gate, and reports exactly which
missing rows it would append, restricted to strictly before the
surviving log's earliest capture. --apply appends them via the same
append-only writer everything else uses. Ledger untouched.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vpredict import config                       # noqa: E402
from vpredict.odds.rebuild import rebuild_report  # noqa: E402
from vpredict.odds.schema import append_captures  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(config.DATA_DIR))
    ap.add_argument("--apply", action="store_true",
                    help="append the missing rows (default: dry run)")
    args = ap.parse_args()

    rep = rebuild_report(args.data)
    print(f"raw dir: {rep['raw_dir']}")
    for src, inv in rep["raw_inventory"].items():
        print(f"  {src}: {inv['files']} daily files "
              f"({inv['first']} .. {inv['last']})")
    print(f"live log: {rep['log_rows']} rows, earliest "
          f"{rep['log_earliest']}")
    print(f"rebuild cutoff (strictly before): {rep['cutoff']}")
    print(f"candidates to append: {rep['n_candidates']}")
    for mid, kinds in rep["matches_restored"].items():
        print(f"  {mid}: {kinds}")
    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0
    n = append_captures(rep["candidates"],
                        path=Path(args.data) / "odds" / "odds.jsonl")
    print(f"\nAPPLIED: appended {n} rows (append-only). The next markets "
          "tick rebuilds picks; rerun scripts/gap_audit.py after it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
