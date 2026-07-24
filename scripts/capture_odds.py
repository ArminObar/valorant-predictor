#!/usr/bin/env python3
"""Capture odds for the frozen predictions — runs on the Mac, cron-friendly.

    python scripts/capture_odds.py --once                 # one pass, all sources
    python scripts/capture_odds.py --once --sources cloudbet
    python scripts/capture_odds.py --once --debug         # + pinnacle intercept dump
    python scripts/capture_odds.py --from-file data/processed/upcoming_predictions.json

Each pass: read the live frozen-prediction set (the public /api/upcoming),
fetch every source's Valorant fixtures, link them to predictions
(exact-normalised names, then the alias table, else stored UNLINKED and
reported), and append captures to the append-only log. Capture kinds:

  freeze  first capture of a (source, match) after its prediction appears
  close   first capture within ODDS_CLOSE_WINDOW_MIN of start_ts

State is derived from the log itself, so re-runs are idempotent and a cron
of `--once` every 10 minutes implements the whole §13 timing spec: the
freeze capture lands on the first pass after the prediction freezes, the
close capture on the last passes before start. Matches already started are
skipped and counted (a missed close is reported, never backfilled).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from vpredict import config
from vpredict.odds import cloudbet
from vpredict.odds.schema import (append_captures, capture_state,
                                  link_fixture, load_aliases)

log = logging.getLogger("vpredict.capture")


def load_predictions(from_file: str | None) -> list[dict]:
    if from_file:
        payload = json.loads(open(from_file, encoding="utf-8").read())
    else:
        import requests
        r = requests.get(config.ODDS_UPCOMING_URL, timeout=20)
        r.raise_for_status()
        payload = r.json()
    return payload.get("predictions", [])


def decide_kind(match_start: datetime, state_slot: dict,
                now: datetime) -> str | None:
    """freeze -> close -> nothing, per (source, match)."""
    if now >= match_start:
        return None                                   # started: missed
    if not state_slot["freeze"]:
        return "freeze"
    in_close = now >= match_start - timedelta(
        minutes=config.ODDS_CLOSE_WINDOW_MIN)
    if in_close and not state_slot["close"]:
        return "close"
    return None


def run_once(sources: list[str], from_file: str | None,
             debug: bool) -> dict:
    now = datetime.now(timezone.utc)
    predictions = load_predictions(from_file)
    by_id = {p["match_id"]: p for p in predictions}
    aliases = load_aliases()
    state = capture_state()
    counters = {"appended": 0, "unlinked": 0, "skipped_started": 0,
                "already_captured": 0, "source_errors": 0}

    for source in sources:
        try:
            if source == "cloudbet":
                fixtures = cloudbet.fetch_valorant_fixtures(now, "freeze")
            elif source == "pinnacle":
                from vpredict.odds import pinnacle
                dbg = (config.ODDS_DIR / "debug") if debug else None
                fixtures = pinnacle.fetch_valorant_fixtures(now, "freeze",
                                                            debug_dir=dbg)
            else:
                log.error("unknown source %s", source)
                continue
        except Exception as e:
            log.error("source %s failed: %s", source, e)
            counters["source_errors"] += 1
            continue

        to_append = []
        for cap in fixtures:
            mid, home_is_t1, method = link_fixture(
                cap.book_home, cap.book_away, predictions, aliases)
            cap.match_id, cap.book_home_is_team1 = mid, home_is_t1
            cap.link_method = method
            if mid is None:
                counters["unlinked"] += 1
                log.info("UNLINKED %s fixture: %s vs %s — add to %s if it "
                         "belongs to a frozen prediction",
                         source, cap.book_home, cap.book_away,
                         config.ODDS_ALIASES_JSON)
                to_append.append(cap)     # stored anyway, per §13
                continue
            start = datetime.fromisoformat(
                by_id[mid]["start_ts"].replace("Z", "+00:00"))
            slot = state.setdefault((source, mid),
                                    {"freeze": False, "close": False})
            kind = decide_kind(start, slot, now)
            if kind is None:
                key = ("skipped_started" if now >= start
                       else "already_captured")
                counters[key] += 1
                continue
            cap.capture_kind = kind
            slot[kind] = True
            to_append.append(cap)
        counters["appended"] += append_captures(to_append)

    return {"ts": now.isoformat(), "predictions": len(by_id), **counters}


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="one pass (cron this)")
    ap.add_argument("--sources", default="cloudbet,pinnacle",
                    help="comma-separated; cloudbet first is the harness")
    ap.add_argument("--from-file", default=None,
                    help="read predictions from a local upcoming_predictions"
                         ".json instead of the live API")
    ap.add_argument("--debug", action="store_true",
                    help="dump pinnacle's intercepted responses")
    args = ap.parse_args()
    if not args.once:
        print("Nothing to do: pass --once (put it on a 10-minute cron).")
        return 2
    out = run_once([s.strip() for s in args.sources.split(",") if s.strip()],
                   args.from_file, args.debug)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
