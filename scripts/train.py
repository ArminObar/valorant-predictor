#!/usr/bin/env python3
"""Train and persist the serving bundle (same pipeline scripts/evaluate.py
evaluates: fit on train, select+calibrate on validation, chronological)."""
import argparse

from vpredict import config
from vpredict.modeling.train import train_and_save


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(config.MATCHES_JSONL))
    ap.add_argument("--half-life", type=float, default=config.DEFAULT_HALF_LIFE_DAYS)
    ap.add_argument("--roster-factor", type=float, default=config.DEFAULT_ROSTER_FACTOR)
    args = ap.parse_args()
    info = train_and_save(args.data, half_life_days=args.half_life,
                          roster_factor=args.roster_factor)
    if info["synthetic"]:
        print("=" * 60 + "\n  SYNTHETIC DATA — this bundle is a demo artifact\n" + "=" * 60)
    print(f"saved {info['path']}")
    print(f"model={info['model']} calibrator={info['calibrator']} "
          f"val_ll={info['val_ll']:.4f} elo_k_baseline={info['elo_k_baseline']:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
