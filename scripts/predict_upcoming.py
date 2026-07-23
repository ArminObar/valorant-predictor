#!/usr/bin/env python3
"""Predict upcoming matches, write the frozen ledger, publish the API JSON.

    python scripts/predict_upcoming.py            # read data/raw/upcoming.jsonl
    python scripts/predict_upcoming.py --crawl    # fetch the vlr.gg upcoming list
"""
import argparse
from datetime import datetime, timezone

from vpredict import config
from vpredict.data import store
from vpredict.modeling.predict import run_predictions
from vpredict.modeling.train import load_bundle
from vpredict.serving.ledger import Ledger


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--crawl", action="store_true",
                    help="fetch the upcoming list from vlr.gg (polite crawler)")
    ap.add_argument("--data", default=str(config.MATCHES_JSONL))
    args = ap.parse_args()

    bundle_path = config.MODELS_DIR / "model.joblib"
    if not bundle_path.exists():
        print("No trained bundle. Run: python scripts/train.py")
        return 1
    bundle = load_bundle(bundle_path)
    if bundle.get("synthetic_data"):
        print("=" * 60 + "\n  WARNING: bundle was trained on SYNTHETIC data\n" + "=" * 60)

    now = datetime.now(timezone.utc)
    if args.crawl:
        from vpredict.scraping.crawl import crawl_upcoming
        upcoming = crawl_upcoming()
    else:
        try:
            upcoming = store.load_matches(config.UPCOMING_JSONL)
        except FileNotFoundError:
            print(f"No {config.UPCOMING_JSONL}; run with --crawl on a machine "
                  "with vlr.gg access, or place an upcoming.jsonl there.")
            return 1
    upcoming = [m for m in upcoming
                if m.start_ts > now and m.status in ("upcoming", "live")]
    if not upcoming:
        print("No future matches to predict.")
        return 0

    history = store.load_matches(args.data)
    led = Ledger()
    counters = run_predictions(bundle, history, upcoming, led, now=now)
    led.close()
    print(f"{len(upcoming)} upcoming matches | ledger: {counters}")
    print(f"published {config.PROCESSED_DIR / 'upcoming_predictions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
