"""Rebuild lost capture-log rows from the raw response archive
(ASSUMPTIONS §67, LOG entry 62).

The odds log lost its head (every row before 2026-07-29T19:39:25) to an
operational truncation in the 2026-08-08 window. /data/raw exists for
exactly this moment: append_raw stores every full response body with
its fetched_at, "so every capture is re-derivable from what the book
actually said". This module replays those bodies through the CURRENT
production code — parse_competition_events for extraction, link_fixture
for linking (raw-identity-first plus the time gate), decide_kind driven
with simulated slots for freeze/close stamping, priceable() as the
gate — and emits only rows the live log is missing.

Scope, stated: linked, priceable freeze/close rows only. Suspended
rows are not resynthesized (§58 excludes them by policy everywhere
now), and unlinked fixtures from the lost window are not resynthesized
either (their matches are graded; §64 restricts any future relink to
not-yet-graded matches, so they have no remaining consumer).

Safety: additions are restricted to fetched_at strictly BEFORE the
current log's earliest captured_at minus a guard, so reconstructed
rows can never near-duplicate surviving originals (whose captured_at
differs from fetched_at by seconds); a key-level diff runs as a second
belt. Apply is append-only via append_captures. The ledger is never
touched; restored rows restore picks that were publicly live before
their matches, repair of a recorded loss, never retroactive insertion.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config
from .capture import decide_kind
from .cloudbet import parse_competition_events
from .schema import OddsCapture, link_fixture, priceable

GUARD_S = 60          # stay clear of the surviving head by this margin


def _ts(v) -> datetime:
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _key(c: OddsCapture) -> tuple:
    """The ingest endpoint's identity key, duplicated deliberately so the
    rebuild dedupes exactly the way a push would."""
    return (c.source, c.book_home, c.book_away, c.market, c.line,
            c.capture_kind, c.captured_at.isoformat())


def iter_raw_records(raw_dir: Path, source: str):
    """(fetched_at, body_dict) for every OK response of `source`, in
    fetched order across the daily files."""
    for path in sorted(raw_dir.glob(f"{source}-*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("status") != 200:
                    continue
                if source == "cloudbet" and \
                        "/competitions/" not in rec.get("url", ""):
                    continue
                try:
                    body = json.loads(rec["body"])
                except (ValueError, TypeError):
                    continue
                yield _ts(rec["fetched_at"]), body


def candidates_from_raw(raw_records, ledger_rows: list[dict],
                        aliases: dict, cutoff: datetime | None,
                        existing_keys: set | None = None) -> list[OddsCapture]:
    """Replay raw bodies into the linked, priceable freeze/close rows the
    original capture loop would have appended, restricted to before
    `cutoff`. Deterministic; pure aside from the iterators."""
    existing_keys = existing_keys or set()
    fixtures: list[OddsCapture] = []
    for fetched_at, body in raw_records:
        if cutoff is not None and fetched_at >= cutoff:
            continue
        got, _keys = parse_competition_events(body, fetched_at, "freeze")
        fixtures.extend(got)
    fixtures.sort(key=lambda c: c.captured_at)

    starts = {str(r["match_id"]): _ts(r["start_ts"]) for r in ledger_rows}
    slots: dict = defaultdict(lambda: {"freeze": False, "close": False})
    out: list[OddsCapture] = []
    for c in fixtures:
        mid, home_is_t1, method = link_fixture(
            c.book_home, c.book_away, ledger_rows, aliases,
            book_start_ts=c.book_start_ts)
        if not mid:
            continue                                    # scope: linked only
        if not priceable(c):
            continue                                    # §58 at every door
        slot = slots[(c.source, mid, c.market, c.line)]
        kind = decide_kind(starts[str(mid)], slot, c.captured_at)
        if kind is None:
            continue                # started, or slot already satisfied
        slot[kind] = True
        c.match_id = mid
        c.book_home_is_team1 = home_is_t1
        c.link_method = method
        c.capture_kind = kind
        if _key(c) in existing_keys:
            continue
        out.append(c)
    return out


def rebuild_report(data_dir: Path | str = config.DATA_DIR,
                   cutoff_override: datetime | None = None) -> dict:
    """Dry-run inventory + candidates. Reads everything, writes nothing."""
    from ..serving.ledger import Ledger
    from .schema import iter_captures, load_aliases

    data_dir = Path(data_dir)
    raw_dir = data_dir / "raw" / "odds" if \
        (data_dir / "raw" / "odds").exists() else config.ODDS_RAW_DIR
    log_path = data_dir / "odds" / "odds.jsonl"

    existing = list(iter_captures(log_path)) if log_path.exists() else []
    existing_keys = {_key(c) for c in existing}
    earliest = min((c.captured_at for c in existing), default=None)
    cutoff = cutoff_override or (
        earliest - timedelta(seconds=GUARD_S) if earliest else None)

    led = Ledger(data_dir / "serving" / "ledger.sqlite")
    try:
        rows = led.rows(graded=None, limit=100000)
    finally:
        led.close()
    aliases = load_aliases(data_dir / "odds" / "aliases.json")

    inv = {}
    for src in ("cloudbet", "pinnacle"):
        files = sorted(p.name for p in raw_dir.glob(f"{src}-*.jsonl"))
        inv[src] = {"files": len(files),
                    "first": files[0] if files else None,
                    "last": files[-1] if files else None}

    cands = candidates_from_raw(
        iter_raw_records(raw_dir, "cloudbet"), rows, aliases, cutoff,
        existing_keys)
    per_match: dict = defaultdict(lambda: {"freeze": 0, "close": 0})
    for c in cands:
        per_match[str(c.match_id)][c.capture_kind] += 1
    return {"raw_dir": str(raw_dir), "raw_inventory": inv,
            "log_rows": len(existing),
            "log_earliest": earliest.isoformat() if earliest else None,
            "cutoff": cutoff.isoformat() if cutoff else None,
            "candidates": cands,
            "n_candidates": len(cands),
            "matches_restored": {m: dict(k) for m, k in
                                 sorted(per_match.items())}}
