#!/usr/bin/env python3
"""Standing Markets coverage-gap audit (ASSUMPTIONS §64). Read-only.

Render Shell (after this ships in the image):
    python3 scripts/gap_audit.py
Anywhere else, against any data root:
    python3 scripts/gap_audit.py --data /path/to/data

Reads serving/ledger.sqlite, odds/odds.jsonl, processed/markets.json,
odds/aliases.json under the data root; prints the partition of every
graded match with a sum check; writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vpredict import config                               # noqa: E402
from vpredict.odds.coverage_audit import classify, render  # noqa: E402
from vpredict.odds.schema import iter_captures, load_aliases  # noqa: E402
from vpredict.serving.ledger import Ledger                 # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(config.DATA_DIR),
                    help="data root (default: config.DATA_DIR)")
    args = ap.parse_args()
    root = Path(args.data)

    led = Ledger(root / "serving" / "ledger.sqlite")
    try:
        graded = led.rows(graded=True, limit=100000)
        pending_n = len(led.rows(graded=False, limit=100000))
    finally:
        led.close()

    captures = list(iter_captures(root / "odds" / "odds.jsonl"))
    mk_path = root / "processed" / "markets.json"
    mk = (json.loads(mk_path.read_text(encoding="utf-8"))
          if mk_path.exists() else {})
    aliases = load_aliases(root / "odds" / "aliases.json")

    result = classify(graded, captures, mk.get("picks", []), aliases)
    print(render(result, mk.get("picks", []),
                 {"generated_at": mk.get("generated_at"),
                  "builder": mk.get("builder"),
                  "skipped": mk.get("skipped")}, pending_n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
