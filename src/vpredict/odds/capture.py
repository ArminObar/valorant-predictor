"""Odds capture, importable: shared by scripts/capture_odds.py (Mac cron,
Pinnacle needs a real browser) and the server refresh cycle (Cloudbet is
plain REST). One implementation, two homes (ASSUMPTIONS §42).

Capture kinds per (source, match, market, line): freeze first, then close
inside ODDS_CLOSE_WINDOW_MIN of start. State derives from the log itself,
so every pass is idempotent. Unlinked fixtures are stored and reported,
never dropped (§13).
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config
from . import cloudbet
from .schema import (OddsCapture, append_captures, capture_state,
                     iter_captures, link_fixture, load_aliases, priceable)

log = logging.getLogger("vpredict.capture")


def load_predictions(from_file: str | None = None,
                     prefer_local: bool = False) -> list[dict]:
    """The frozen prediction set to link fixtures against.

    Server side (prefer_local): read the published JSON straight from disk;
    the refresh cycle that just wrote it is the same process tree, and an
    HTTP round-trip to ourselves adds a failure mode for nothing. Mac side:
    fetch the live API as before.
    """
    if from_file:
        payload = json.loads(Path(from_file).read_text(encoding="utf-8"))
        return payload.get("predictions", [])
    local = config.PROCESSED_DIR / "upcoming_predictions.json"
    if prefer_local and local.exists():
        payload = json.loads(local.read_text(encoding="utf-8"))
        return payload.get("predictions", [])
    import requests
    r = requests.get(config.ODDS_UPCOMING_URL, timeout=20)
    r.raise_for_status()
    return r.json().get("predictions", [])


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


def run_once(sources: list[str], from_file: str | None = None,
             debug: bool = False, prefer_local: bool = False,
             log_path: Path | None = None,
             ) -> tuple[dict, list[OddsCapture]]:
    """One capture pass. Returns (report, records appended this pass)."""
    now = datetime.now(timezone.utc)
    log_path = log_path or config.ODDS_JSONL
    predictions = load_predictions(from_file, prefer_local=prefer_local)
    by_id = {p["match_id"]: p for p in predictions}
    aliases = load_aliases()
    state = capture_state(log_path)
    seen_unlinked = {(c.source, c.book_event_id, c.market, c.line)
                     for c in iter_captures(log_path) if c.match_id is None}
    counters = {"appended": 0, "unlinked": 0, "skipped_started": 0,
                "already_captured": 0, "skipped_unpriceable": 0,
                "source_errors": 0}
    appended: list[OddsCapture] = []

    for source in sources:
        try:
            if source == "cloudbet":
                fixtures = cloudbet.fetch_valorant_fixtures(now, "freeze")
            elif source == "pinnacle":
                from . import pinnacle
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
                cap.book_home, cap.book_away, predictions, aliases,
                book_start_ts=cap.book_start_ts)
            cap.match_id, cap.book_home_is_team1 = mid, home_is_t1
            cap.link_method = method
            if mid is None:
                counters["unlinked"] += 1
                ukey = (source, cap.book_event_id, cap.market, cap.line)
                if ukey not in seen_unlinked:
                    # One stored record per unlinked fixture: enough for
                    # suggest_aliases and for any later relink, without the
                    # 10-minute tick appending a duplicate every pass for
                    # the whole listing window (LOG entry 61).
                    seen_unlinked.add(ukey)
                    log.info("UNLINKED %s fixture: %s vs %s — add to %s if "
                             "it belongs to a frozen prediction",
                             source, cap.book_home, cap.book_away,
                             config.ODDS_ALIASES_JSON)
                    to_append.append(cap)     # stored once, per §13
                continue
            start = datetime.fromisoformat(
                by_id[mid]["start_ts"].replace("Z", "+00:00"))
            slot = state.setdefault((source, mid, cap.market, cap.line),
                                    {"freeze": False, "close": False})
            kind = decide_kind(start, slot, now)
            if kind is None:
                key = ("skipped_started" if now >= start
                       else "already_captured")
                counters[key] += 1
                continue
            if not priceable(cap):
                # A suspended/placeholder price is not a capture. Recording
                # it here used to mark the slot done, so the one freeze this
                # match would ever get was burned on a 0.0 and the market
                # shipped close-only with a fabricated CLV of exactly 0.0
                # (LOG entry 59). Count it, say so, retry next pass.
                counters["skipped_unpriceable"] += 1
                log.info("UNPRICEABLE %s %s: %s vs %s at %s/%s — slot left "
                         "open, will retry", source, kind, cap.book_home,
                         cap.book_away, cap.price_home, cap.price_away)
                continue
            cap.capture_kind = kind
            slot[kind] = True
            to_append.append(cap)
        counters["appended"] += append_captures(to_append, path=log_path)
        appended.extend(to_append)

    return {"ts": now.isoformat(), "predictions": len(by_id),
            **counters}, appended


def acquire_capture_lock(path: Path | None = None):
    """Non-blocking exclusive lock so overlapping fires can't race the
    append-only log (two concurrent passes both derive 'no freeze yet' from
    the log and would both append one). Returns the held file object, or
    None when another capture is running. fcntl.flock is per open file
    description and releases automatically if the process dies — no stale
    lockfile handling needed. Works on macOS and Linux.
    """
    path = path or (config.ODDS_DIR / ".capture.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def recent_captures(hours: float | None = None,
                    log_path: Path | None = None,
                    now: datetime | None = None) -> list[OddsCapture]:
    """Every local record captured inside the window — the --push payload.
    Re-sending records the server already holds is free (ingest dedupes),
    so a push that failed yesterday is healed by today's fire instead of
    silently losing that run's records forever (LOG entry 46, secondary)."""
    hours = config.ODDS_PUSH_WINDOW_H if hours is None else hours
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    return [c for c in iter_captures(log_path or config.ODDS_JSONL)
            if _aware(c.captured_at) >= cutoff]


# ------------------------------------------------------------------ push
def push_captures(records: list[OddsCapture],
                  base_url: str | None = None,
                  token: str | None = None,
                  batch: int = 500) -> dict:
    """POST capture records to the server's odds ingest. The server
    validates every record against the same schema and dedupes by record
    identity, so pushing is idempotent and re-runs are safe."""
    import requests
    base = (base_url or os.environ.get("VPREDICT_BASE_URL")
            or config.VPREDICT_BASE_URL).rstrip("/")
    token = token or os.environ.get("VPREDICT_INGEST_TOKEN")
    if not token:
        raise RuntimeError("VPREDICT_INGEST_TOKEN not set; cannot push")
    totals = {"received": 0, "appended": 0, "duplicates": 0, "invalid": 0}
    for i in range(0, len(records), batch):
        chunk = [json.loads(c.model_dump_json()) for c in
                 records[i:i + batch]]
        r = requests.post(f"{base}/api/ingest/odds",
                          json={"captures": chunk},
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=30)
        r.raise_for_status()
        for k, v in r.json().items():
            if k in totals:
                totals[k] += v
    return totals
