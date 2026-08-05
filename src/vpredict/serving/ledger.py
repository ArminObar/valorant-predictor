"""The prediction ledger — the scoreboard's source of truth.

Integrity rules (the whole point of a public scoreboard):
- A prediction is accepted only if it is logged at least
  LEDGER_FREEZE_MARGIN_S (5 min) BEFORE the match's scheduled start.
- The FIRST prediction for a match is frozen; later calls are ignored, even
  from a newer model version. "Called in advance" means the earliest call
  stands.
- Rows are never updated except by grading (filling in the observed result).
- The Elo baseline's probability is stored alongside the model's at the same
  moment, so the scoreboard always shows the comparison the model must win.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .. import config
from ..data.schema import Match

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
  match_id      TEXT PRIMARY KEY,
  made_at       TEXT NOT NULL,
  start_ts      TEXT NOT NULL,
  team1         TEXT, team2 TEXT,
  team1_name    TEXT, team2_name TEXT,
  event         TEXT,
  best_of       INTEGER,
  p_model       REAL NOT NULL,
  p_elo         REAL NOT NULL,
  model_version TEXT,
  low_history   INTEGER DEFAULT 0,
  graded        INTEGER DEFAULT 0,
  team1_won     INTEGER,
  graded_at     TEXT
);
"""

# Columns added after first ship, applied as idempotent ALTERs so existing
# ledgers upgrade in place. p_maps_dist freezes the model's maps-played
# distribution WITH the first prediction (the map-totals analogue of
# p_model — recomputing it later would let a newer model rewrite the public
# totals call); maps_played is grading metadata for totals markets.
_MIGRATIONS = [
    ("p_maps_dist", "ALTER TABLE predictions ADD COLUMN p_maps_dist TEXT"),
    ("maps_played", "ALTER TABLE predictions ADD COLUMN maps_played INTEGER"),
]

_EPS = 1e-6


def _maps_played(m: Match) -> int | None:
    """Maps actually played, for totals grading: the series score when the
    parser has it, else the count of parsed map blocks, else None."""
    if m.team1_maps is not None and m.team2_maps is not None:
        return int(m.team1_maps) + int(m.team2_maps)
    return len(m.maps) or None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class Ledger:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else config.LEDGER_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.path)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(_SCHEMA)
        have = {r["name"] for r in self._con.execute(
            "PRAGMA table_info(predictions)")}
        for col, ddl in _MIGRATIONS:
            if col not in have:
                self._con.execute(ddl)
        self._con.commit()

    # ---------------------------------------------------------------- writes
    def insert_prediction(self, *, match_id: str, start_ts: datetime,
                          team1: str, team2: str, team1_name: str,
                          team2_name: str, event: str, best_of: int,
                          p_model: float, p_elo: float, model_version: str,
                          low_history: bool = False,
                          p_maps_dist: dict | None = None,
                          now: datetime | None = None) -> str:
        """Returns 'inserted' | 'frozen' (already predicted) | 'too_late'."""
        now = now or _now()
        margin = (start_ts - now).total_seconds()
        if margin < config.LEDGER_FREEZE_MARGIN_S:
            return "too_late"
        import json as _json
        cur = self._con.execute(
            "INSERT OR IGNORE INTO predictions "
            "(match_id, made_at, start_ts, team1, team2, team1_name, team2_name,"
            " event, best_of, p_model, p_elo, model_version, low_history,"
            " p_maps_dist) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (match_id, _iso(now), _iso(start_ts), team1, team2, team1_name,
             team2_name, event, int(best_of), float(p_model), float(p_elo),
             model_version, int(bool(low_history)),
             _json.dumps(p_maps_dist) if p_maps_dist else None))
        self._con.commit()
        return "inserted" if cur.rowcount == 1 else "frozen"

    @staticmethod
    def _placeholder(name: str | None) -> bool:
        return (name or "").strip().lower() in {"", "tbd", "tba"}

    def grade(self, matches: Iterable[Match], now: datetime | None = None) -> int:
        """Fill observed results for ungraded rows whose match completed with a
        winner, and backfill placeholder team names ("TBD") with the real
        names the completed match carries. Names are display metadata, like
        start_ts (ASSUMPTIONS §15): the frozen probabilities and keys record
        what was known at call time and are untouched. Returns number graded.

        Accepts any iterable and holds no Match objects: the ungraded-id set
        (small) comes from sqlite first, then the stream is scanned once. The
        old version built a dict of every completed match — a full-store
        materialization inside the refresh cycle (LOG entry 22).
        """
        now = now or _now()
        ungraded = {r["match_id"] for r in self._con.execute(
            "SELECT match_id FROM predictions WHERE graded = 0")}
        if not ungraded:
            return 0
        graded = 0
        for m in matches:
            if (m.match_id in ungraded and m.status == "completed"
                    and m.winner):
                self._con.execute(
                    "UPDATE predictions SET graded=1, team1_won=?, graded_at=?,"
                    " maps_played=? WHERE match_id=? AND graded=0",
                    (int(m.winner == "team1"), _iso(now), _maps_played(m),
                     m.match_id))
                if ((self._placeholder(m.team1_name) is False
                     or self._placeholder(m.team2_name) is False)):
                    self._con.execute(
                        "UPDATE predictions SET team1_name=?, team2_name=?"
                        " WHERE match_id=? AND (LOWER(TRIM(team1_name)) IN"
                        " ('', 'tbd', 'tba') OR LOWER(TRIM(team2_name)) IN"
                        " ('', 'tbd', 'tba'))",
                        (m.team1_name, m.team2_name, m.match_id))
                graded += 1
                ungraded.discard(m.match_id)
                if not ungraded:
                    break
        self._con.commit()
        return graded

    def resolve_placeholder_names(self, match_id, team1, team2,
                                  team1_name: str, team2_name: str) -> bool:
        """Adopt resolved identities for placeholder sides of a FROZEN row.

        Metadata only (§57): a side whose stored key is a placeholder
        ("tbd") takes the resolved key and display name; the call itself —
        probabilities, pick, versions, timestamps, grading — is never
        touched, and a real stored key is never overwritten. A placeholder
        is also never written over anything: resolution only ever moves a
        side from placeholder to real. Returns True when a row changed."""
        row = self._con.execute(
            "SELECT team1, team2 FROM predictions WHERE match_id = ?",
            (str(match_id),)).fetchone()
        if row is None:
            return False

        def _ph(k) -> bool:
            return str(k).strip().lower() in config.PLACEHOLDER_TEAM_KEYS

        sets, args = [], []
        if _ph(row["team1"]) and not _ph(team1):
            sets += ["team1 = ?", "team1_name = ?"]
            args += [str(team1), team1_name]
        if _ph(row["team2"]) and not _ph(team2):
            sets += ["team2 = ?", "team2_name = ?"]
            args += [str(team2), team2_name]
        if not sets:
            return False
        args.append(str(match_id))
        with self._con:
            self._con.execute(
                f"UPDATE predictions SET {', '.join(sets)} WHERE match_id = ?",
                args)
        return True

    def backfill_names(self, matches: Iterable[Match]) -> int:
        """One-time sweep for rows graded before grade() learned to backfill
        placeholder names. Same stream discipline as backfill_maps_played."""
        need = {r["match_id"] for r in self._con.execute(
            "SELECT match_id FROM predictions WHERE"
            " LOWER(TRIM(team1_name)) IN ('', 'tbd', 'tba')"
            " OR LOWER(TRIM(team2_name)) IN ('', 'tbd', 'tba')")}
        if not need:
            return 0
        fixed = 0
        for m in matches:
            if (m.match_id in need and m.status == "completed"
                    and not self._placeholder(m.team1_name)
                    and not self._placeholder(m.team2_name)):
                self._con.execute(
                    "UPDATE predictions SET team1_name=?, team2_name=?"
                    " WHERE match_id=?",
                    (m.team1_name, m.team2_name, m.match_id))
                fixed += 1
                need.discard(m.match_id)
                if not need:
                    break
        self._con.commit()
        return fixed

    def backfill_maps_played(self, matches: Iterable[Match]) -> int:
        """Fill maps_played for rows graded BEFORE the column existed.
        Grading metadata only — probabilities and outcomes are untouched.
        Same streaming shape as grade(); cheap when nothing is missing."""
        missing = {r["match_id"] for r in self._con.execute(
            "SELECT match_id FROM predictions "
            "WHERE graded = 1 AND maps_played IS NULL")}
        if not missing:
            return 0
        filled = 0
        for m in matches:
            if m.match_id in missing and m.status == "completed":
                n = _maps_played(m)
                if n:
                    self._con.execute(
                        "UPDATE predictions SET maps_played=? WHERE match_id=?",
                        (n, m.match_id))
                    filled += 1
                missing.discard(m.match_id)
                if not missing:
                    break
        self._con.commit()
        return filled

    # ---------------------------------------------------------------- reads
    def rows(self, graded: bool | None = None, limit: int = 300,
             ascending: bool = False) -> list[dict]:
        """Ordering decides who survives the LIMIT, so it must match the
        list's purpose: graded lists want the newest results (DESC, the
        default), a pending list wants the matches about to start (ASC).
        The audit found the pending endpoint using DESC, which silently
        dropped exactly the soonest matches once pending passed the cap."""
        q = "SELECT * FROM predictions"
        if graded is not None:
            q += f" WHERE graded = {1 if graded else 0}"
        q += f" ORDER BY start_ts {'ASC' if ascending else 'DESC'} LIMIT ?"
        return [dict(r) for r in self._con.execute(q, (limit,))]

    def summary(self) -> dict:
        g = self.rows(graded=True, limit=100000)
        pending = self._con.execute(
            "SELECT COUNT(*) c FROM predictions WHERE graded = 0").fetchone()["c"]

        def metrics(ps: list[float], ys: list[int]) -> dict | None:
            if not ys:
                return None
            n = len(ys)
            lls, brs, acc = 0.0, 0.0, 0
            for p, y in zip(ps, ys):
                p = min(max(p, _EPS), 1 - _EPS)
                lls += -(y * math.log(p) + (1 - y) * math.log(1 - p))
                brs += (p - y) ** 2
                acc += int((p >= 0.5) == bool(y))
            return {"n": n, "log_loss": lls / n, "brier": brs / n,
                    "accuracy": acc / n}

        # Headline metrics score graded NON-low-history rows only, the same
        # pre-registered convention the backtest uses (ASSUMPTIONS §16): a
        # low-history call (e.g. a TBD placeholder bracket slot) is part of
        # the frozen record and shown, but it measures the prior, not the
        # model. Both counts are reported so nothing is hidden.
        scored = [r for r in g if not r["low_history"]]
        ys = [int(r["team1_won"]) for r in scored]
        return {
            "n_pending": int(pending),
            "n_graded": len(g),
            "n_low_history": len(g) - len(scored),
            "n_scored": len(scored),
            "model": metrics([r["p_model"] for r in scored], ys),
            "elo": metrics([r["p_elo"] for r in scored], ys),
        }

    def close(self) -> None:
        self._con.close()
