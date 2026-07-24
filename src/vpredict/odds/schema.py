"""Odds capture records, the append-only log, and match linking.

One `OddsCapture` per (source, match, capture moment). Raw decimal prices
only — de-vig happens at analysis time (`devig.py`). The log is append-only
JSONL; captures are never edited or deleted, and re-runs are idempotent
because capture state (has this match a freeze/close from this source
already?) is derived by scanning the log itself.

Linking book fixtures to vlr matches is conservative by design: an exact
match on normalised team-name pairs, else a user-maintained alias table,
else the capture is stored UNLINKED (match_id null) with candidates logged —
never a silent fuzzy guess (ASSUMPTIONS §13/§14).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from .. import config


class OddsCapture(BaseModel):
    captured_at: datetime
    source: str                    # "cloudbet" | "pinnacle" | ...
    capture_kind: str              # "freeze" | "close"
    market: str = "series_moneyline"
    # Book-side identity, stored verbatim for auditability:
    book_event_id: str
    book_home: str
    book_away: str
    book_start_ts: datetime | None = None
    book_market_key: str | None = None
    # Decimal prices as the book listed them (home/away in BOOK orientation):
    price_home: float
    price_away: float
    # Link to our world (None = unlinked; see linking notes above):
    match_id: str | None = None
    book_home_is_team1: bool | None = None
    link_method: str | None = None  # "exact" | "alias" | None


def append_captures(captures: list[OddsCapture],
                    path: Path = config.ODDS_JSONL) -> int:
    """Append-only write. No rewrite, no dedupe — the log is the record."""
    if not captures:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for c in captures:
            f.write(c.model_dump_json() + "\n")
    return len(captures)


def iter_captures(path: Path = config.ODDS_JSONL):
    if not Path(path).exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield OddsCapture.model_validate_json(line)


def capture_state(path: Path = config.ODDS_JSONL) -> dict:
    """{(source, match_id_or_book_event_id): {"freeze": bool, "close": bool}}
    derived from the log — the only state the capture loop needs."""
    state: dict = {}
    for c in iter_captures(path):
        key = (c.source, c.match_id or f"book:{c.book_event_id}")
        slot = state.setdefault(key, {"freeze": False, "close": False})
        if c.capture_kind in slot:
            slot[c.capture_kind] = True
    return state


def append_raw(source: str, url: str, status: int, body: str,
               raw_dir: Path = config.ODDS_RAW_DIR) -> None:
    """Append-only raw-response log, one file per source per UTC day, so
    every capture is re-derivable from what the book actually said."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rec = {"fetched_at": datetime.now(timezone.utc).isoformat(),
           "url": url, "status": status, "body": body}
    with open(raw_dir / f"{source}-{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# ------------------------------------------------------------------ linking

_STRIP = re.compile(r"[^a-z0-9]+")


def normalize_team(name: str) -> str:
    return _STRIP.sub("", (name or "").casefold())


def load_aliases(path: Path = config.ODDS_ALIASES_JSON) -> dict[str, str]:
    """User-maintained overrides: normalised book name -> normalised vlr
    name. Edited by hand when the capture log reports unlinked fixtures."""
    if not Path(path).exists():
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {normalize_team(k): normalize_team(v) for k, v in raw.items()}


def link_fixture(book_home: str, book_away: str, predictions: list[dict],
                 aliases: dict[str, str] | None = None
                 ) -> tuple[str | None, bool | None, str | None]:
    """Match a book fixture to one frozen prediction.

    Returns (match_id, book_home_is_team1, method). Predictions are the
    dicts the public /api/upcoming serves (team1_name/team2_name/match_id).
    Exact normalised pair match first (either orientation), then the alias
    table; anything else is (None, None, None) and the caller logs it.
    """
    aliases = aliases or {}

    def canon(name: str) -> str:
        n = normalize_team(name)
        return aliases.get(n, n)

    h, a = canon(book_home), canon(book_away)
    for p in predictions:
        t1, t2 = normalize_team(p["team1_name"]), normalize_team(p["team2_name"])
        if (h, a) == (t1, t2):
            return p["match_id"], True, "exact" if (
                normalize_team(book_home), normalize_team(book_away)
            ) == (t1, t2) else "alias"
        if (h, a) == (t2, t1):
            return p["match_id"], False, "exact" if (
                normalize_team(book_home), normalize_team(book_away)
            ) == (t2, t1) else "alias"
    return None, None, None
