"""Show the current map-pool decision from the real store, both ways.

Read-only. Prints, at a given moment: per-map in-window play counts, the
recency-weighted counts (config half-life), last-played dates, and the pool
each rule selects. Every pool number in ASSUMPTIONS §36 and the 2026-07-26
session report regenerates from here.

    python scripts/inspect_pool.py                       # now = wall clock
    python scripts/inspect_pool.py --now 2026-07-24T00:04:32Z

Respects VPREDICT_DATA like everything else.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd

from vpredict import config
from vpredict.data import store
from vpredict.modeling.predict import current_pool, pool_table


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--now", default=None,
                    help="ISO timestamp for the as-of moment (default: now)")
    ap.add_argument("--window", type=int,
                    default=config.CURRENT_POOL_WINDOW_DAYS)
    ap.add_argument("--half-life", type=float,
                    default=config.CURRENT_POOL_HALF_LIFE_DAYS)
    ap.add_argument("--size", type=int, default=config.CURRENT_POOL_SIZE)
    args = ap.parse_args()

    now = (pd.Timestamp(args.now) if args.now
           else pd.Timestamp(datetime.now(timezone.utc)))
    if now.tzinfo is None:
        now = now.tz_localize("UTC")

    maps_df = store.maps_frame(store.iter_matches(config.MATCHES_JSONL))
    tbl = pool_table(maps_df, now, window_days=args.window,
                     half_life_days=args.half_life)
    raw = current_pool(maps_df, now, window_days=args.window,
                       size=args.size, half_life_days=None)
    weighted = current_pool(maps_df, now, window_days=args.window,
                            size=args.size, half_life_days=args.half_life)

    print(f"as of {now.isoformat()}  window={args.window}d  "
          f"half-life={args.half_life}d  pool size={args.size}")
    out = tbl.copy()
    out["weighted"] = out["weighted"].round(2)
    out["last_played"] = pd.to_datetime(out["last_played"]).dt.date
    print(out.to_string())
    print(f"\nraw-count pool (old rule):        {raw}")
    print(f"recency-weighted pool (serving):  {weighted}")
    joined = sorted(set(weighted) - set(raw))
    dropped = sorted(set(raw) - set(weighted))
    if joined or dropped:
        print(f"difference: +{joined}  -{dropped}")


if __name__ == "__main__":
    main()
