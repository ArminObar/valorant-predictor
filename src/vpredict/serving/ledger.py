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

_EPS = 1e-6


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
        self._con.commit()

    # ---------------------------------------------------------------- writes
    def insert_prediction(self, *, match_id: str, start_ts: datetime,
                          team1: str, team2: str, team1_name: str,
                          team2_name: str, event: str, best_of: int,
                          p_model: float, p_elo: float, model_version: str,
                          low_history: bool = False,
                          now: datetime | None = None) -> str:
        """Returns 'inserted' | 'frozen' (already predicted) | 'too_late'."""
        now = now or _now()
        margin = (start_ts - now).total_seconds()
        if margin < config.LEDGER_FREEZE_MARGIN_S:
            return "too_late"
        cur = self._con.execute(
            "INSERT OR IGNORE INTO predictions "
            "(match_id, made_at, start_ts, team1, team2, team1_name, team2_name,"
            " event, best_of, p_model, p_elo, model_version, low_history) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (match_id, _iso(now), _iso(start_ts), team1, team2, team1_name,
             team2_name, event, int(best_of), float(p_model), float(p_elo),
             model_version, int(bool(low_history))))
        self._con.commit()
        return "inserted" if cur.rowcount == 1 else "frozen"

    def grade(self, matches: list[Match], now: datetime | None = None) -> int:
        """Fill observed results for ungraded rows whose match completed with a
        winner. Returns number graded."""
        now = now or _now()
        by_id = {m.match_id: m for m in matches
                 if m.status == "completed" and m.winner}
        graded = 0
        for row in self._con.execute(
                "SELECT match_id FROM predictions WHERE graded = 0"):
            m = by_id.get(row["match_id"])
            if m is None:
                continue
            self._con.execute(
                "UPDATE predictions SET graded=1, team1_won=?, graded_at=? "
                "WHERE match_id=? AND graded=0",
                (int(m.winner == "team1"), _iso(now), row["match_id"]))
            graded += 1
        self._con.commit()
        return graded

    # ---------------------------------------------------------------- reads
    def rows(self, graded: bool | None = None, limit: int = 300) -> list[dict]:
        q = "SELECT * FROM predictions"
        if graded is not None:
            q += f" WHERE graded = {1 if graded else 0}"
        q += " ORDER BY start_ts DESC LIMIT ?"
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

        ys = [int(r["team1_won"]) for r in g]
        return {
            "n_pending": int(pending),
            "n_graded": len(g),
            "model": metrics([r["p_model"] for r in g], ys),
            "elo": metrics([r["p_elo"] for r in g], ys),
        }

    def close(self) -> None:
        self._con.close()
