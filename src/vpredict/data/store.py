"""Persistence + the analytical frame.

Raw truth lives in JSONL (one Match per line, idempotent upsert by match_id).
`maps_frame()` flattens it into the long table used by every downstream module:
one row per (match, map, team).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from .. import config
from .schema import Match


# --------------------------------------------------------------------------- raw store
def _iter_lines(path: Path):
    """(line_index, stripped_line) for every nonblank line."""
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if line:
                yield i, line


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _capped_line_indices(path: Path, n: int) -> set[int] | None:
    """Line indices of the chronologically FIRST n records, or None when the
    cap does not bite. Pass 1 of the capped read parses only start_ts per
    line (per-line transient), so simulating a smaller store never costs a
    full parse — the growth curve's dominant term must scale with n."""
    stamps = [(_parse_ts(json.loads(line)["start_ts"]), i)
              for i, line in _iter_lines(path)]
    if n >= len(stamps):
        return None
    return {i for _, i in sorted(stamps)[:n]}


def iter_matches(path: Path = config.MATCHES_JSONL) -> Iterator[Match]:
    """Stream the store one validated Match at a time — the only way the
    refresh cycle is allowed to read it. Nothing in the cycle may hold the
    full store: two coexisting full materializations were ~85% of the OOM
    footprint (LOG entry 22).

    Honors VPREDICT_STORE_LIMIT with load_matches's exact semantics
    (chronologically FIRST n, lean two-pass selection). Yield order is file
    order, which upsert_matches keeps sorted by (start_ts, match_id).
    """
    if not Path(path).exists():
        return
    limit = os.environ.get("VPREDICT_STORE_LIMIT")
    keep: set[int] | None = None
    if limit and int(limit) > 0:
        keep = _capped_line_indices(path, int(limit))
    for i, line in _iter_lines(path):
        if keep is None or i in keep:
            yield Match.model_validate_json(line)


def load_matches(path: Path = config.MATCHES_JSONL) -> list[Match]:
    """Materialized read — fine for scripts, tests, and small files
    (upcoming.jsonl). The refresh cycle and the crawler must use
    iter_matches / the streaming upsert instead."""
    return list(iter_matches(path))


def count_matches(path: Path = config.MATCHES_JSONL) -> int:
    """Record count without parsing records (one per nonblank line). Honors
    VPREDICT_STORE_LIMIT so measurement runs see a consistent world."""
    if not Path(path).exists():
        return 0
    total = sum(1 for _ in _iter_lines(path))
    limit = os.environ.get("VPREDICT_STORE_LIMIT")
    if limit and 0 < int(limit) < total:
        return int(limit)
    return total


def upsert_matches(new: Iterable[Match], path: Path = config.MATCHES_JSONL) -> int:
    """Insert or replace by match_id. Returns number of new/updated records.

    Streaming sorted merge, memory O(batch). The store file is kept sorted by
    (start_ts, match_id) — an invariant this function maintains — so the
    existing file and the sorted new batch merge line-by-line into a tmp file
    (atomic tmp+replace, unchanged). The old implementation materialized the
    entire store on every call, which made each 250-match crawl flush cost a
    full-store copy in memory (LOG entry 23). Pass-through lines are copied
    verbatim without re-validation; only colliding lines are parsed into
    Match, to preserve the exact changed-count semantics.
    """
    new_sorted = sorted(new, key=lambda m: (m.start_ts, m.match_id))
    if not new_sorted:
        return 0
    new_ids = {m.match_id for m in new_sorted}
    if len(new_ids) != len(new_sorted):
        # last-wins within a batch, matching the old dict-build semantics
        dedup: dict[str, Match] = {m.match_id: m for m in new_sorted}
        new_sorted = sorted(dedup.values(), key=lambda m: (m.start_ts, m.match_id))

    exists = Path(path).exists()
    changed = 0
    colliding: set[str] = set()
    if exists:
        for _, line in _iter_lines(path):
            mid = json.loads(line)["match_id"]
            if mid in new_ids:
                colliding.add(mid)
    changed += len(new_ids - colliding)          # brand-new records

    by_id = {m.match_id: m for m in new_sorted}
    tmp = Path(str(path) + ".tmp")
    j = 0
    with open(tmp, "w", encoding="utf-8") as out_f:
        if exists:
            for _, line in _iter_lines(path):
                d = json.loads(line)
                line_key = (_parse_ts(d["start_ts"]), d["match_id"])
                while j < len(new_sorted) and (
                        (new_sorted[j].start_ts, new_sorted[j].match_id)
                        < line_key):
                    out_f.write(new_sorted[j].model_dump_json() + "\n")
                    j += 1
                if d["match_id"] in colliding:
                    prev = Match.model_validate_json(line)
                    if prev.model_dump() != by_id[d["match_id"]].model_dump():
                        changed += 1
                    continue                      # replacement merges in sorted
                out_f.write(line + "\n")
        while j < len(new_sorted):
            out_f.write(new_sorted[j].model_dump_json() + "\n")
            j += 1
    tmp.replace(path)
    return changed


# --------------------------------------------------------------------------- analytical frame
def _team_row(m: Match, mp, which: str) -> dict:
    other = "team2" if which == "team1" else "team1"
    own_players = mp.team1_players if which == "team1" else mp.team2_players
    own_econ = mp.team1_econ if which == "team1" else mp.team2_econ
    own_score = mp.team1_score if which == "team1" else mp.team2_score
    opp_score = mp.team2_score if which == "team1" else mp.team1_score
    own_ct = mp.team1_ct if which == "team1" else mp.team2_ct
    own_t = mp.team1_t if which == "team1" else mp.team2_t
    opp_ct = mp.team2_ct if which == "team1" else mp.team1_ct
    opp_t = mp.team2_t if which == "team1" else mp.team1_t

    fk = sum(p.fk or 0 for p in own_players) if own_players else None
    fd = sum(p.fd or 0 for p in own_players) if own_players else None
    lineup = tuple(sorted(p.name.strip().lower() for p in own_players if p.name.strip()))

    pistols_won, pistols_played = 0, 0
    for r in mp.rounds:
        if r.number in (1, 13) and r.winner:
            pistols_played += 1
            if r.winner == which:
                pistols_won += 1

    mk = sum(p.multikills for p in own_players) if own_players and all(
        p.multikills is not None for p in own_players) else None
    cl = sum(p.clutch_wins for p in own_players) if own_players and all(
        p.clutch_wins is not None for p in own_players) else None

    def _pair(t):
        return (t[0], t[1]) if t else (None, None)

    fb_n, fb_w = _pair(own_econ.full_buy) if own_econ else (None, None)
    low_n = low_w = None
    if own_econ and own_econ.eco is not None and own_econ.semi_eco is not None:
        low_n = own_econ.eco[0] + own_econ.semi_eco[0]
        low_w = own_econ.eco[1] + own_econ.semi_eco[1]

    return {
        "match_id": m.match_id,
        "start_ts": pd.Timestamp(m.start_ts).tz_convert("UTC") if pd.Timestamp(m.start_ts).tzinfo
        else pd.Timestamp(m.start_ts, tz="UTC"),
        "best_of": m.best_of,
        "event": m.event,
        "series": m.series,
        "team": m.key_team(which),                 # stable key
        "team_name": getattr(m, f"{which}_name"),
        "opp": m.key_team(other),
        "opp_name": getattr(m, f"{other}_name"),
        "is_team1": which == "team1",
        "map_name": mp.map_name,
        "map_index": mp.index,
        "won": int(own_score > opp_score),
        "rounds_won": own_score,
        "rounds_lost": opp_score,
        # Side splits (regulation only; None when unavailable)
        "atk_rw": own_t, "atk_rl": opp_ct, "def_rw": own_ct, "def_rl": opp_t,
        "fk": fk, "fd": fd,
        "pistols_won": pistols_won, "pistols_played": pistols_played,
        "lineup": lineup,
        "multikills": mk, "clutch_wins": cl,
        "fullbuy_n": fb_n, "fullbuy_w": fb_w, "lowbuy_n": low_n, "lowbuy_w": low_w,
        "synthetic": m.synthetic,
    }


def maps_frame(matches: Iterable[Match] | None = None, path: Path = config.MATCHES_JSONL) -> pd.DataFrame:
    """Long frame: one row per (completed match, map, team)."""
    if matches is None:
        matches = iter_matches(path)
    rows: list[dict] = []
    for m in matches:
        if m.status != "completed":
            continue
        for mp in m.maps:
            if mp.team1_score == mp.team2_score:      # abandoned/invalid map
                continue
            rows.append(_team_row(m, mp, "team1"))
            rows.append(_team_row(m, mp, "team2"))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values(["start_ts", "match_id", "map_index", "team"]).reset_index(drop=True)
    return df


def matches_frame(matches: Iterable[Match] | None = None, path: Path = config.MATCHES_JSONL) -> pd.DataFrame:
    """One row per completed match with series outcome."""
    if matches is None:
        matches = iter_matches(path)
    rows = []
    for m in matches:
        if m.status != "completed" or not m.winner:
            continue
        rows.append({
            "match_id": m.match_id,
            "start_ts": pd.Timestamp(m.start_ts).tz_convert("UTC") if pd.Timestamp(m.start_ts).tzinfo
            else pd.Timestamp(m.start_ts, tz="UTC"),
            "best_of": m.best_of,
            "event": m.event, "series": m.series,
            "team1": m.key_team("team1"), "team2": m.key_team("team2"),
            "team1_name": m.team1_name, "team2_name": m.team2_name,
            "team1_won": int(m.winner == "team1"),
            "n_maps": len(m.maps),
            "synthetic": m.synthetic,
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["start_ts", "match_id"]).reset_index(drop=True)


def is_playoff(series: str) -> bool:
    s = (series or "").lower()
    return any(k in s for k in ("playoff", "final", "semifinal", "quarterfinal",
                                "upper bracket", "lower bracket", "knockout", "elimination"))
