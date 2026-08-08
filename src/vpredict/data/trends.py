"""Team trends: rows, scoped aggregation, and the two preset views
(ASSUMPTIONS §61 and §63).

The store is decomposed once per full cycle into one row per
(team, map) — the trends fact table — and every view is an aggregation
over those rows: the all-history default, the current-form preset
(§61's original last-10/active-60 window), and any owner-requested
custom scope by date range and tournament. One set of metric
definitions, so views cannot drift from each other.

No-fabrication rules (§63, same discipline as the unit tracker):
scopes clamp to the data that exists; a metric whose per-map inputs are
absent excludes that map from BOTH numerator and denominator (kills and
first-kill columns included, tightening §61's per-field rule to map
grain), and renders null when nothing remains — never a zero-filled
estimate. Clutch and economy trends stay absent entirely: the store has
never held their inputs (Tier B, unscraped).

Round records are the regulation strip, so pistols and the method mix
are regulation-only; spreads and combined kills use the full map score
including overtime.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .. import config
from .schema import Match

# vlr's event line concatenates "Tournament" + "Stage/Phase" blocks with
# raw whitespace; the phase block starts at one of these keywords. The
# split is a display heuristic for the tournament picker, pinned by test
# on the real dirty shapes; a miss leaves the collapsed full string,
# which is visible in the index rather than silently wrong (§63).
_PHASE = re.compile(
    r"(League Phase|Group Stage|Playoffs|Main Event|Knockout|Swiss|"
    r"Week \d|Opening Matches|Grand Final|Qualifier)")


def normalize_event(ev: str | None) -> str:
    s = re.sub(r"\s+", " ", ev or "").strip()
    m = _PHASE.search(s)
    head = s[:m.start()].strip(" :-") if m else s
    return head or "(unknown event)"


def _ts(v) -> datetime:
    if isinstance(v, datetime):
        dt = v
    else:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _team_map_row(m: Match, mp, t: int, event_id: int) -> dict:
    """One completed map from team t's (1 or 2) perspective. Short keys:
    this dict is the on-disk artifact row (thousands of them)."""
    own = mp.team1_score if t == 1 else mp.team2_score
    opp = mp.team2_score if t == 1 else mp.team1_score
    me = f"team{t}"
    pp = pw = 0
    methods = [0, 0, 0, 0]                      # elim, boom, defuse, time
    order = {"elim": 0, "boom": 1, "defuse": 2, "time": 3}
    for r in mp.rounds or []:
        if r.number in (1, 13) and r.winner:
            pp += 1
            pw += r.winner == me
        if r.winner == me and r.win_method in order:
            methods[order[r.win_method]] += 1
    players = (mp.team1_players if t == 1 else mp.team2_players) or []
    opp_players = (mp.team2_players if t == 1 else mp.team1_players) or []
    both = players + opp_players
    kills_ok = bool(both) and all(p.kills is not None for p in both)
    fk_ok = bool(players) and all(
        p.fk is not None and p.fd is not None for p in players)
    return {
        "t": None,                              # filled by caller (team id)
        "ts": _ts(m.start_ts).isoformat(),
        "e": event_id,
        "w": int(own > opp), "sp": own - opp, "r": own + opp,
        "pp": pp, "pw": pw,
        "ko": int(kills_ok),
        "ck": (sum(p.kills or 0 for p in both) if kills_ok else 0),
        "fo": int(fk_ok),
        "fk": (sum(p.fk or 0 for p in players) if fk_ok else 0),
        "fd": (sum(p.fd or 0 for p in players) if fk_ok else 0),
        "m": methods,
        "ag": [p.agent for p in players if p.agent],
    }


def team_map_rows(matches: Iterable[Match],
                  now: datetime | None = None) -> dict:
    """The trends fact table: rows plus the team-name map and the
    normalized tournament index (name, match count, date span)."""
    now = now or datetime.now(timezone.utc)
    rows: list[dict] = []
    names: dict[str, str] = {}
    tour_ids: dict[str, int] = {}
    tours: list[dict] = []
    ordered = sorted((m for m in matches
                      if m.status == "completed" and m.maps),
                     key=lambda m: m.start_ts)
    for m in ordered:
        ev = normalize_event(m.event)
        if ev not in tour_ids:
            tour_ids[ev] = len(tours)
            tours.append({"id": len(tours), "name": ev, "n_matches": 0,
                          "first": None, "last": None})
        rec = tours[tour_ids[ev]]
        rec["n_matches"] += 1
        d = _ts(m.start_ts).isoformat()
        rec["first"] = d if rec["first"] is None else min(rec["first"], d)
        rec["last"] = d if rec["last"] is None else max(rec["last"], d)
        for t, tid, tname in ((1, m.team1_id, m.team1_name),
                              (2, m.team2_id, m.team2_name)):
            if not tid:
                continue
            names[tid] = tname or names.get(tid, "")
            for mp in m.maps:
                row = _team_map_row(m, mp, t, tour_ids[ev])
                row["t"] = tid
                rows.append(row)
    return {"generated_at": now.isoformat(), "rows": rows,
            "teams": names, "tournaments": tours}


def aggregate(table: dict, *, min_maps: int,
              window_maps: int | None = None,
              active_days: int | None = None,
              date_from: datetime | None = None,
              date_to: datetime | None = None,
              event_name: str | None = None,
              now: datetime | None = None) -> dict:
    """One team table over a scope of the fact rows. window_maps keeps
    only each team's most recent N in-scope maps (the current-form
    preset); active_days hides teams with no map at all since the
    cutoff (current-form only — a historical scope must show the teams
    of its era, §63)."""
    now = now or datetime.now(timezone.utc)
    event_id = None
    if event_name is not None:
        for rec in table["tournaments"]:
            if rec["name"] == event_name:
                event_id = rec["id"]
                break
        if event_id is None:                    # unknown name: empty view,
            return {"n_teams": 0, "teams": []}  # never an error (§63)
    per_team: dict[str, list[dict]] = defaultdict(list)
    lifetime: Counter = Counter()
    last_any: dict[str, str] = {}
    for row in table["rows"]:
        tid = row["t"]
        lifetime[tid] += 1
        last_any[tid] = max(last_any.get(tid, ""), row["ts"])
        if event_id is not None and row["e"] != event_id:
            continue
        ts = _ts(row["ts"])
        if date_from is not None and ts < date_from:
            continue
        if date_to is not None and ts > date_to:
            continue
        per_team[tid].append(row)

    cutoff = (now - timedelta(days=active_days)).isoformat() \
        if active_days is not None else None
    teams = []
    for tid, entries in per_team.items():
        if len(entries) < min_maps:
            continue
        if cutoff is not None and last_any.get(tid, "") < cutoff:
            continue
        entries.sort(key=lambda r: r["ts"])
        w = entries[-window_maps:] if window_maps else entries
        n = len(w)
        ck_maps = [e for e in w if e["ko"]]
        fk_maps = [e for e in w if e["fo"]]
        fk_rounds = sum(e["r"] for e in fk_maps)
        pist_played = sum(e["pp"] for e in w)
        methods = [sum(e["m"][i] for e in w) for i in range(4)]
        won_known = sum(methods)
        agents: Counter = Counter()
        for e in w:
            agents.update(e["ag"])
        teams.append({
            "team_id": tid,
            "name": table["teams"].get(tid, tid),
            "n_lifetime": lifetime[tid], "n_window": n,
            "last_map_ts": w[-1]["ts"],
            "win_rate": round(sum(e["w"] for e in w) / n, 4),
            "spread_avg": round(sum(e["sp"] for e in w) / n, 2),
            "pistol_wr": (round(sum(e["pw"] for e in w) / pist_played, 4)
                          if pist_played else None),
            "comb_kills_avg": (round(sum(e["ck"] for e in ck_maps)
                                     / len(ck_maps), 1)
                               if ck_maps else None),
            "fk_diff12": (round(12.0 * sum(e["fk"] - e["fd"]
                                           for e in fk_maps) / fk_rounds, 2)
                          if fk_rounds else None),
            "method_mix": ({k: round(methods[i] / won_known, 4)
                            for i, k in enumerate(
                                ("elim", "boom", "defuse", "time"))}
                           if won_known else None),
            "agents_top": [{"agent": a, "n": c}
                           for a, c in agents.most_common(5)],
        })
    teams.sort(key=lambda r: (-r["n_window"], -r["spread_avg"], r["name"]))
    return {"n_teams": len(teams), "teams": teams}


def build_trends(matches: Iterable[Match],
                 now: datetime | None = None) -> dict:
    """The §61 current-form view, unchanged in shape and semantics:
    last TRENDS_WINDOW_MAPS per team, TRENDS_MIN_LIFETIME_MAPS lifetime,
    active inside TRENDS_ACTIVE_DAYS."""
    now = now or datetime.now(timezone.utc)
    table = team_map_rows(matches, now=now)
    view = aggregate(table, min_maps=config.TRENDS_MIN_LIFETIME_MAPS,
                     window_maps=config.TRENDS_WINDOW_MAPS,
                     active_days=config.TRENDS_ACTIVE_DAYS, now=now)
    return {
        "generated_at": now.isoformat(),
        "params": {"window_maps": config.TRENDS_WINDOW_MAPS,
                   "active_days": config.TRENDS_ACTIVE_DAYS,
                   "min_lifetime_maps": config.TRENDS_MIN_LIFETIME_MAPS},
        "n_teams": view["n_teams"],
        "teams": view["teams"],
    }


def build_trends_bundle(matches: Iterable[Match],
                        now: datetime | None = None) -> tuple[dict, dict]:
    """(fact table artifact, precomputed views file) for the full cycle.
    The views file carries the all-history default and the current-form
    preset plus the tournament index; custom scopes aggregate the
    artifact at request time (§63)."""
    now = now or datetime.now(timezone.utc)
    table = team_map_rows(matches, now=now)
    common = {"generated_at": now.isoformat(),
              "params": {"window_maps": config.TRENDS_WINDOW_MAPS,
                         "active_days": config.TRENDS_ACTIVE_DAYS,
                         "min_lifetime_maps": config.TRENDS_MIN_LIFETIME_MAPS,
                         "scope_min_maps": config.TRENDS_SCOPE_MIN_MAPS},
              "tournaments": table["tournaments"]}
    views = {
        "all": {**aggregate(table, min_maps=config.TRENDS_SCOPE_MIN_MAPS,
                            now=now),
                "scope": {"preset": "all"}},
        "current": {**aggregate(
            table, min_maps=config.TRENDS_MIN_LIFETIME_MAPS,
            window_maps=config.TRENDS_WINDOW_MAPS,
            active_days=config.TRENDS_ACTIVE_DAYS, now=now),
            "scope": {"preset": "current_form"}},
    }
    return table, {**common, "views": views}
