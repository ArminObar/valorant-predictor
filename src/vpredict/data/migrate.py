"""One-time timezone migration of stored start times (LOG entry 29).

Every `start_ts` written before the parser fix came from vlr.gg's
`data-utc-ts` attribute stamped as UTC, but the attribute actually carries
the wall clock in vlr's default display timezone (US Eastern) for cookieless
clients. Every stored start is therefore 4 h (EDT) or 5 h (EST) early.

This migration reinterprets each stored timestamp's naive wall time as
America/New_York and converts it to true UTC — exactly what re-parsing the
immutable HTML cache with the fixed parser produces, without needing the
cache. It touches:

  - data/raw/matches.jsonl   (re-sorted afterwards: the +4/+5 h shift is not
                              uniform across DST boundaries, and the store's
                              (start_ts, match_id) sort order is an invariant)
  - data/raw/upcoming.jsonl  (if present)
  - the ledger's start_ts    (metadata correction ONLY — made_at, p_model,
                              p_elo and every other frozen field are
                              untouched; the freeze property "made_at >= 5 min
                              before start" becomes strictly MORE true, since
                              true starts are 4-5 h later than recorded)

A marker file makes the migration run-once: applying it twice would shift
times a second time. The marker also stores an audit report, including a
cross-check against book-reported start times from the odds log when one
exists (Cloudbet serves genuine UTC, so linked captures independently
confirm the correction).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import config
from .schema import Match

log = logging.getLogger("vpredict.migrate")

_SITE_TZ = ZoneInfo("America/New_York")


def marker_path() -> Path:
    """Resolved lazily so tests that re-root config paths are honored."""
    return config.RAW_DIR / ".tz_migration_v1.json"


def _shift(dt: datetime) -> datetime:
    """Reinterpret a mislabeled-UTC timestamp as ET wall time -> true UTC.

    fold=0 on the ambiguous fall-back hour (first occurrence, EDT); the
    nonexistent spring-forward hour is mapped forward by zoneinfo. Both are
    <=1 h, apply to at most one wall-clock hour per year, and match the fixed
    parser's behaviour exactly.
    """
    naive = dt.replace(tzinfo=None)
    return naive.replace(tzinfo=_SITE_TZ).astimezone(timezone.utc)


def tz_migration_applied() -> bool:
    return marker_path().exists()


def _migrate_jsonl(path: Path) -> int:
    """Shift start_ts on every record, keep the (start_ts, match_id) sort
    invariant, atomic tmp+replace. Round-trips through the Match model so the
    on-disk format stays exactly what upsert_matches writes.

    One-shot maintenance path: holds the serialized lines (strings, not
    models) in memory once — acceptable for a run-once migration, and far
    lighter than the old full-store materialization the streaming refactor
    removed.
    """
    if not path.exists():
        return 0
    out: list[tuple[datetime, str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = Match.model_validate_json(line)
            m.start_ts = _shift(m.start_ts)
            out.append((m.start_ts, m.match_id, m.model_dump_json()))
    out.sort(key=lambda t: (t[0], t[1]))
    tmp = path.with_suffix(path.suffix + ".tzmig.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for _, _, line in out:
            f.write(line + "\n")
    tmp.replace(path)
    return len(out)


def _migrate_ledger(ledger_path: Path) -> int:
    if not ledger_path.exists():
        return 0
    con = sqlite3.connect(ledger_path)
    try:
        rows = con.execute("SELECT match_id, start_ts FROM predictions").fetchall()
        for match_id, ts in rows:
            fixed = _shift(datetime.fromisoformat(ts))
            con.execute("UPDATE predictions SET start_ts=? WHERE match_id=?",
                        (fixed.astimezone(timezone.utc).isoformat(), match_id))
        con.commit()
        return len(rows)
    finally:
        con.close()


def _crosscheck_odds(ledger_path: Path, odds_path: Path) -> dict | None:
    """Compare corrected ledger starts with book-reported UTC starts for
    linked captures. Purely informational: books list their own cutoff, which
    can differ from vlr's listing by a few minutes."""
    if not (odds_path.exists() and ledger_path.exists()):
        return None
    book_start: dict[str, datetime] = {}
    with open(odds_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            mid, ts = rec.get("match_id"), rec.get("book_start_ts")
            if mid and ts:
                book_start.setdefault(
                    mid, datetime.fromisoformat(ts.replace("Z", "+00:00")))
    if not book_start:
        return None
    con = sqlite3.connect(ledger_path)
    try:
        deltas = []
        for mid, bts in book_start.items():
            row = con.execute("SELECT start_ts FROM predictions WHERE match_id=?",
                              (mid,)).fetchone()
            if row:
                ours = datetime.fromisoformat(row[0])
                deltas.append(abs((ours - bts).total_seconds()) / 60.0)
        if not deltas:
            return None
        return {"n_linked_checked": len(deltas),
                "max_abs_delta_min": round(max(deltas), 1),
                "mean_abs_delta_min": round(sum(deltas) / len(deltas), 1)}
    finally:
        con.close()


def migrate_tz_if_needed(matches_path: Path | None = None,
                         upcoming_path: Path | None = None,
                         ledger_path: Path | None = None,
                         marker: Path | None = None,
                         odds_path: Path | None = None,
                         force: bool = False) -> dict:
    """Idempotent entry point — safe to call at the top of every refresh
    cycle. Returns the audit report (or the stored one if already applied).
    Path arguments exist for tests; production callers pass nothing.

    ``force=True`` skips the marker check and re-applies the shift — ONLY for
    the documented re-seeding case (old-format data copied onto a disk whose
    marker was written earlier). Forcing on already-migrated data corrupts it.
    """
    marker = marker or marker_path()
    if marker.exists() and not force:
        return json.loads(marker.read_text(encoding="utf-8"))
    matches_path = matches_path or config.MATCHES_JSONL
    upcoming_path = upcoming_path or config.UPCOMING_JSONL
    ledger_path = ledger_path or config.LEDGER_PATH
    log.warning("applying one-time timezone migration (LOG entry 29): "
                "reinterpreting stored start_ts as US-Eastern wall time -> UTC")
    report = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "n_matches": _migrate_jsonl(matches_path),
        "n_upcoming": _migrate_jsonl(upcoming_path),
        "n_ledger_rows": _migrate_ledger(ledger_path),
    }
    check = _crosscheck_odds(ledger_path, odds_path or config.ODDS_JSONL)
    if check:
        report["odds_crosscheck"] = check
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(report, indent=1), encoding="utf-8")
    log.warning("timezone migration done: %s", report)
    return report
