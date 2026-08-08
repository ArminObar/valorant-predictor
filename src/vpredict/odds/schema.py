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
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from .. import config

log = logging.getLogger("vpredict.schema")


class OddsCapture(BaseModel):
    captured_at: datetime
    source: str                    # "cloudbet" | "pinnacle" | ...
    capture_kind: str              # "freeze" | "close"
    market: str = "series_moneyline"
    # For "maps_total" rows: the over/under line (e.g. 2.5), and by
    # convention price_home = OVER, price_away = UNDER. Moneyline rows keep
    # line = None and the book's real home/away orientation.
    line: float | None = None
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


def priceable(c: OddsCapture) -> bool:
    """A usable two-sided price: both decimals finite and above 1.0.
    Everything else is a placeholder or feed glitch, not a price: 0.0
    (suspended markets), negatives, and NaN or inf, which pass ordinary
    comparisons unnoticed because NaN compares False with everything
    (LOG entry 47). Shared by the capture loop and the markets build so
    "counts as captured" and "counts as a price" can never disagree
    (LOG entry 59)."""
    return (math.isfinite(c.price_home) and math.isfinite(c.price_away)
            and c.price_home > 1.0 and c.price_away > 1.0)


def capture_state(path: Path = config.ODDS_JSONL) -> dict:
    """{(source, match_id_or_book_event_id, market, line):
        {"freeze": bool, "close": bool}} derived from the log — the only
    state the capture loop needs. Keyed per market/line so a moneyline
    freeze doesn't suppress the totals freeze for the same match.
    Pre-totals log rows have no line field and land under line=None.
    Only priceable rows count toward a slot: a suspended 0.0 first
    sighting must not consume the one freeze this match will ever get
    (LOG entry 59). Historical unpriceable rows in the log are thereby
    un-burned on the first pass after this rule shipped."""
    state: dict = {}
    for c in iter_captures(path):
        if not priceable(c):
            continue
        key = (c.source, c.match_id or f"book:{c.book_event_id}",
               c.market, c.line)
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
                 aliases: dict[str, str] | None = None,
                 book_start_ts=None,
                 ) -> tuple[str | None, bool | None, str | None]:
    """Match a book fixture to one frozen prediction.

    Returns (match_id, book_home_is_team1, method). Predictions are the
    dicts the public /api/upcoming serves (team1_name/team2_name/match_id).
    Two rules harden this against alias poisoning (LOG entry 61):

    1. RAW identity beats alias redirect. The raw normalised pair is
       scanned against every prediction before any alias is applied, so
       an alias mapping one real org's name onto another can never steal
       a fixture whose own teams are already on the board.
    2. Start-time gate. When the book supplies a start time, a candidate
       whose prediction start differs by more than
       ODDS_LINK_MAX_START_DELTA_H hours is rejected (and logged), so a
       name-pair coincidence days away cannot cross-link. No book start
       means no gate, as before.

    Anything unmatched is (None, None, None) and the caller logs it.
    """
    aliases = aliases or {}

    def _within_gate(p: dict) -> bool:
        if book_start_ts is None:
            return True
        try:
            ps = datetime.fromisoformat(
                str(p["start_ts"]).replace("Z", "+00:00"))
            bs = book_start_ts
            if isinstance(bs, str):
                bs = datetime.fromisoformat(bs.replace("Z", "+00:00"))
            if ps.tzinfo is None:
                ps = ps.replace(tzinfo=timezone.utc)
            if bs.tzinfo is None:
                bs = bs.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError, TypeError):
            return True                    # unparseable: do not guess
        delta_h = abs((ps - bs).total_seconds()) / 3600.0
        if delta_h > config.ODDS_LINK_MAX_START_DELTA_H:
            log.warning(
                "LINK GATE: '%s vs %s' name-matches %s but starts %.1f h "
                "apart (> %s h); refusing the link", book_home, book_away,
                p.get("match_id"), delta_h,
                config.ODDS_LINK_MAX_START_DELTA_H)
            return False
        return True

    raw = (normalize_team(book_home), normalize_team(book_away))
    ali = (aliases.get(raw[0], raw[0]), aliases.get(raw[1], raw[1]))
    for pair, method in ((raw, "exact"), (ali, "alias")):
        if method == "alias" and pair == raw:
            break                          # no alias applied: nothing new
        for p in predictions:
            t1 = normalize_team(p["team1_name"])
            t2 = normalize_team(p["team2_name"])
            if pair == (t1, t2) and _within_gate(p):
                return p["match_id"], True, method
            if pair == (t2, t1) and _within_gate(p):
                return p["match_id"], False, method
    return None, None, None
