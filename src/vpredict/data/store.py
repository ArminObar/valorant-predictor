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
from typing import Iterable

import pandas as pd

from .. import config
from .schema import Match


# --------------------------------------------------------------------------- raw store
def _read_matches(path: Path) -> list[Match]:
    """Uncapped reader. upsert_matches MUST use this, never load_matches:
    upsert rewrites the file from what it loaded, so a capped read would
    silently truncate the store."""
    if not Path(path).exists():
        return []
    out: list[Match] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(Match.model_validate_json(line))
    return out


def load_matches(path: Path = config.MATCHES_JSONL) -> list[Match]:
    """Load the store. If VPREDICT_STORE_LIMIT=<n> is set (a measurement aid
    for `memharness.py growth`, never set in production), return only the
    chronologically FIRST n matches — simulating the store as it was when it
    held n matches, which is what a peak-memory-vs-store-size curve needs.

    The capped path deliberately avoids materializing the full store: pass 1
    reads only each line's start_ts (per-line transient), pass 2 validates
    just the selected lines. Capping AFTER a full parse would make the
    growth curve's dominant term (the parse itself) flat in n and the fit
    meaningless — the failure mode memharness's spread warning describes.
    """
    limit = os.environ.get("VPREDICT_STORE_LIMIT")
    if not limit:
        return _read_matches(path)
    n = int(limit)
    if n <= 0 or not Path(path).exists():
        return _read_matches(path)
    stamps: list[tuple[datetime, int]] = []  # (start_ts, line_index)
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if line:
                ts = json.loads(line)["start_ts"]
                stamps.append(
                    (datetime.fromisoformat(ts.replace("Z", "+00:00")), i))
    if n >= len(stamps):
        return _read_matches(path)
    keep = {i for _, i in sorted(stamps)[:n]}
    out: list[Match] = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i in keep:
                out.append(Match.model_validate_json(line.strip()))
    out.sort(key=lambda m: m.start_ts)
    return out


def upsert_matches(new: Iterable[Match], path: Path = config.MATCHES_JSONL) -> int:
    """Insert or replace by match_id. Returns number of new/updated records."""
    existing = {m.match_id: m for m in _read_matches(path)}
    changed = 0
    for m in new:
        prev = existing.get(m.match_id)
        if prev is None or prev.model_dump() != m.model_dump():
            existing[m.match_id] = m
            changed += 1
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for m in sorted(existing.values(), key=lambda x: (x.start_ts, x.match_id)):
            f.write(m.model_dump_json() + "\n")
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


def maps_frame(matches: list[Match] | None = None, path: Path = config.MATCHES_JSONL) -> pd.DataFrame:
    """Long frame: one row per (completed match, map, team)."""
    if matches is None:
        matches = load_matches(path)
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


def matches_frame(matches: list[Match] | None = None, path: Path = config.MATCHES_JSONL) -> pd.DataFrame:
    """One row per completed match with series outcome."""
    if matches is None:
        matches = load_matches(path)
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
