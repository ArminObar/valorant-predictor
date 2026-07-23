"""Baselines: tuned-K Elo and the favourite rule.

The EloBook here serves double duty:
1. It IS the probabilistic baseline the model must beat (tie = legitimate finding).
2. `features/build.py` uses the same book to emit pre-match Elo features, so the
   model and the baseline see identical rating state.

Leakage rule (same as the as-of engine): a match's result is applied to the
ratings only once its ESTIMATED FINISH time (start + assumed duration) has
passed. Updates are held in an event queue and flushed just before each
snapshot, so an overlapping earlier-starting match never leaks into a match
that started before it finished. Both teams of a match are snapshotted ONCE,
before any of that match's own maps update anything (no within-match leak).
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from .. import config
from ..features.asof import add_est_end


# --------------------------------------------------------------------------- match lites
def matches_lite_from_maps(maps_df: pd.DataFrame,
                           extra_maps: dict[str, list[str]] | None = None) -> list[dict]:
    """Collapse the long maps frame into one chronologically sorted dict per
    match, oriented so team `a` is the as-listed team1. `extra_maps` adds
    map names (e.g. veto-known deciders that were never played) to a match's
    Elo snapshot without affecting rating updates."""
    df = add_est_end(maps_df)
    extra_maps = extra_maps or {}
    lites: list[dict] = []
    for mid, g in df.groupby("match_id", sort=False):
        g1 = g[g["is_team1"]].sort_values("map_index")
        if g1.empty:
            continue
        r0 = g1.iloc[0]
        lites.append({
            "match_id": mid,
            "start_ts": r0["start_ts"],
            "est_end_ts": r0["est_end_ts"],
            "a": r0["team"], "b": r0["opp"],
            "a_name": r0["team_name"], "b_name": r0["opp_name"],
            "best_of": int(r0["best_of"]),
            "event": r0.get("event", ""), "series": r0.get("series", ""),
            "synthetic": bool(r0.get("synthetic", False)),
            "maps": [(row.map_name, int(row.won), int(row.map_index))
                     for row in g1.itertuples()],
            "maps_extra": list(extra_maps.get(mid, [])),
        })
    lites.sort(key=lambda d: (d["start_ts"], d["match_id"]))
    return lites


def _snapshot_map_names(lite: dict) -> list[str]:
    names = [m for m, _, _ in lite["maps"]]
    for m in lite.get("maps_extra", []):
        if m and m not in names:
            names.append(m)
    return names


# --------------------------------------------------------------------------- Elo book
@dataclass
class EloBook:
    k: float = config.DEFAULT_ELO_K
    base: float = config.ELO_BASE
    scale: float = config.ELO_SCALE
    blend_m: float = config.MAP_ELO_BLEND_M
    r: dict = field(default_factory=dict)                 # team -> overall rating
    map_r: dict = field(default_factory=dict)             # (team, map) -> raw rating
    map_n: dict = field(default_factory=dict)             # (team, map) -> games on map

    def rating(self, team: str) -> float:
        return self.r.get(team, self.base)

    def expected(self, ra: float, rb: float) -> float:
        return 1.0 / (1.0 + 10.0 ** ((rb - ra) / self.scale))

    def map_effective(self, team: str, map_name: str) -> float:
        """Per-map rating blended toward overall: w = n / (n + M)."""
        n = self.map_n.get((team, map_name), 0)
        raw = self.map_r.get((team, map_name), self.rating(team))
        w = n / (n + self.blend_m)
        return w * raw + (1.0 - w) * self.rating(team)

    def update_map_game(self, a: str, b: str, map_name: str, a_won: int) -> None:
        # Per-map table first (initialised at CURRENT overall on first touch).
        for t in (a, b):
            key = (t, map_name)
            if key not in self.map_r:
                self.map_r[key] = self.rating(t)
                self.map_n[key] = 0
        e_map = self.expected(self.map_r[(a, map_name)], self.map_r[(b, map_name)])
        dm = self.k * (a_won - e_map)
        self.map_r[(a, map_name)] += dm
        self.map_r[(b, map_name)] -= dm
        self.map_n[(a, map_name)] += 1
        self.map_n[(b, map_name)] += 1
        # Overall.
        e = self.expected(self.rating(a), self.rating(b))
        d = self.k * (a_won - e)
        self.r[a] = self.rating(a) + d
        self.r[b] = self.rating(b) - d


def _snapshot(book: EloBook, lite: dict) -> dict:
    ra, rb = book.rating(lite["a"]), book.rating(lite["b"])
    return {
        "elo_a": ra, "elo_b": rb,
        "p_a": book.expected(ra, rb),
        "maps": {m: (book.map_effective(lite["a"], m), book.map_effective(lite["b"], m))
                 for m in _snapshot_map_names(lite)},
    }


def compute_prematch_elo(lites: list[dict], k: float = config.DEFAULT_ELO_K) -> dict[str, dict]:
    """One chronological pass. Returns {match_id: snapshot} where the snapshot
    reflects only matches whose estimated finish precedes this match's start."""
    book = EloBook(k=k)
    pending: list[tuple] = []   # (est_end_ts, seq, updates)
    seq = 0
    table: dict[str, dict] = {}
    for lite in sorted(lites, key=lambda d: (d["start_ts"], d["match_id"])):
        while pending and pending[0][0] <= lite["start_ts"]:
            _, _, updates = heapq.heappop(pending)
            for a, b, m, aw in updates:
                book.update_map_game(a, b, m, aw)
        table[lite["match_id"]] = _snapshot(book, lite)
        updates = [(lite["a"], lite["b"], m, aw) for m, aw, _ in lite["maps"]]
        heapq.heappush(pending, (lite["est_end_ts"], seq, updates))
        seq += 1
    return table


def elo_snapshot_at(lites: list[dict], cutoff: pd.Timestamp, probe: dict,
                    k: float = config.DEFAULT_ELO_K) -> dict:
    """Rating state at an arbitrary cutoff: apply every match whose estimated
    finish is <= cutoff, then snapshot `probe` ({a, b, maps}). Used by the
    build-time leakage spot-check and by upcoming-match prediction."""
    book = EloBook(k=k)
    eligible = [l for l in lites if l["est_end_ts"] <= cutoff]
    # Same application order as the event queue in compute_prematch_elo:
    # by estimated finish, ties broken by start order. Elo updates do not
    # commute, so the order must match exactly for the spot-check to be valid.
    eligible.sort(key=lambda d: (d["est_end_ts"], d["start_ts"], d["match_id"]))
    for lite in eligible:
        for m, aw, _ in lite["maps"]:
            book.update_map_game(lite["a"], lite["b"], m, aw)
    return _snapshot(book, probe)


# --------------------------------------------------------------------------- baseline fitting
def elo_row_probs(table: dict[str, dict], meta: pd.DataFrame) -> np.ndarray:
    """Per map-row P(team A wins), from overall pre-match ratings."""
    return np.array([table[mid]["p_a"] for mid in meta["match_id"]], dtype=float)


def tune_elo_k(
    lites: list[dict],
    meta: pd.DataFrame,
    y: np.ndarray,
    val_mask: np.ndarray,
    k_grid: list[float] | None = None,
) -> tuple[float, np.ndarray, list[tuple[float, float]]]:
    """Pick K by validation log loss. Returns (best_k, probs for ALL rows at
    best K, [(k, val_log_loss), ...]). Test rows are never touched here."""
    k_grid = k_grid or config.ELO_K_GRID
    results: list[tuple[float, float]] = []
    best_k, best_ll, best_probs = None, np.inf, None
    yv = np.asarray(y, dtype=float)
    for k in k_grid:
        probs = elo_row_probs(compute_prematch_elo(lites, k=k), meta)
        ll = log_loss(yv[val_mask], np.clip(probs[val_mask], 1e-6, 1 - 1e-6), labels=[0, 1])
        results.append((k, ll))
        if ll < best_ll:
            best_k, best_ll, best_probs = k, ll, probs
    return float(best_k), best_probs, results
