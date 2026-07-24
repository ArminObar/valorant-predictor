#!/usr/bin/env python3
"""Apply the one-time timezone migration to this machine's store + ledger.

    python scripts/migrate_store_tz.py            # apply (marker-guarded)
    python scripts/migrate_store_tz.py --status   # just report

Background (LOG entry 29): every start_ts stored before the parser fix is
the US-Eastern wall clock mislabeled as UTC — 4 h early in summer, 5 h in
winter. This reinterprets each stored time as America/New_York and converts
to true UTC; a marker file makes re-runs no-ops (running the shift twice
would corrupt the store). Re-parsing the HTML cache with the fixed parser
produces byte-identical start times; this script exists so the correction
doesn't require the cache.

On Render the refresh cycle applies the same migration automatically on its
next run — nothing to do there beyond deploying the code.
"""
from __future__ import annotations

import argparse
import json
import sys

from vpredict.data.migrate import (marker_path, migrate_tz_if_needed,
                                   tz_migration_applied)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true",
                    help="report whether the migration has been applied")
    ap.add_argument("--force", action="store_true",
                    help="re-apply even if the marker exists. ONLY for "
                         "re-seeding old-format data onto a disk that was "
                         "already marked; forcing on migrated data corrupts "
                         "it by shifting a second time.")
    args = ap.parse_args()

    if args.status:
        if tz_migration_applied():
            print("applied:")
            print(marker_path().read_text(encoding="utf-8"))
        else:
            print("NOT applied — stored start times are still 4-5 h early. "
                  "Run without --status to fix.")
        return 0

    already = tz_migration_applied()
    report = migrate_tz_if_needed(force=args.force)
    if already and not args.force:
        print("Already applied — nothing changed. Report from the original run:")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
