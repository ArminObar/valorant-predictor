#!/usr/bin/env python3
"""Print the calibration monitor over the graded ledger (ASSUMPTIONS §13)."""
import json

from vpredict.evaluation.calibration import monitor_report
from vpredict.evaluation.tiers import classify_tier
from vpredict.serving.ledger import Ledger


def main() -> int:
    led = Ledger()
    rows = led.rows(graded=True, limit=100000)
    led.close()
    print(json.dumps(monitor_report(rows, tier_of=classify_tier), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
