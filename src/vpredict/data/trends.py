"""Phase-1 team trends (ASSUMPTIONS §61): derived entirely from data the
scraper already stores. Per team, over its last TRENDS_WINDOW_MAPS
completed maps: map win rate, average round spread, pistol win rate,
average combined kills, first-kill differential per 12 rounds, the
win-method mix of rounds it won, and its most-played agents.

Explicitly NOT here, because the store has never held the inputs:
clutch trends (clutch_wins is a Tier B performance-tab field, 0%
populated across the store) and anything economy-based. Those need new
scraping first and are out of phase 1 by owner scope. Round records are
the regulation strip, so pistols and the method mix are regulation-only;
spreads and totals use the full map score including overtime.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .. import config
from .schema import Match


def _team_map_entry(m: Match, mp, t: int) -> dict:
    """One completed map from team t's (1 or 2) perspective."""
    own = mp.team1_score if t == 1 else mp.team2_score
    opp = mp.team2_score if t == 1 else mp.team1_score
    me = f"team{t}"
    pist_played = pist_won = 0
    methods: Counter = Counter()
    for r in mp.rounds or []:
        if r.number in (1, 13):
            if r.winner:
                pist_played += 1
                pist_won += r.winner == me
        if r.winner == me and r.win_method:
            methods[r.win_method] += 1
    players = (mp.team1_players if t == 1 else mp.team2_players) or []
    opp_players = (mp.team2_players if t == 1 else mp.team1_players) or []
    kills = sum(p.kills or 0 for p in players)
    comb = kills + sum(p.kills or 0 for p in opp_players)
    fk = sum(p.fk or 0 for p in players)
    fd = sum(p.fd or 0 for p in players)
    return {"start_ts": m.start_ts, "won": own > opp,
            "spread": own - opp, "rounds": own + opp,
            "pist_played": pist_played, "pist_won": pist_won,
            "comb_kills": comb, "fk": fk, "fd": fd, "methods": methods,
            "agents": [p.agent for p in players if p.agent]}


def build_trends(matches: Iterable[Match],
                 now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    per_team: dict[str, list[dict]] = defaultdict(list)
    names: dict[str, str] = {}
    ordered = sorted((m for m in matches
                      if m.status == "completed" and m.maps),
                     key=lambda m: m.start_ts)
    for m in ordered:
        for t, tid, tname in ((1, m.team1_id, m.team1_name),
                              (2, m.team2_id, m.team2_name)):
            if not tid:
                continue
            names[tid] = tname or names.get(tid, "")
            for mp in m.maps:
                per_team[tid].append(_team_map_entry(m, mp, t))

    cutoff = now - timedelta(days=config.TRENDS_ACTIVE_DAYS)
    teams = []
    for tid, entries in per_team.items():
        if len(entries) < config.TRENDS_MIN_LIFETIME_MAPS:
            continue
        last = entries[-1]["start_ts"]
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last < cutoff:
            continue
        w = entries[-config.TRENDS_WINDOW_MAPS:]
        n = len(w)
        rounds = sum(e["rounds"] for e in w)
        pist_played = sum(e["pist_played"] for e in w)
        methods: Counter = Counter()
        for e in w:
            methods.update(e["methods"])
        won_known = sum(methods.values())
        agents: Counter = Counter()
        for e in w:
            agents.update(e["agents"])
        teams.append({
            "team_id": tid, "name": names.get(tid, tid),
            "n_lifetime": len(entries), "n_window": n,
            "last_map_ts": entries[-1]["start_ts"].isoformat(),
            "win_rate": round(sum(e["won"] for e in w) / n, 4),
            "spread_avg": round(sum(e["spread"] for e in w) / n, 2),
            "pistol_wr": (round(sum(e["pist_won"] for e in w)
                                / pist_played, 4) if pist_played else None),
            "comb_kills_avg": round(sum(e["comb_kills"] for e in w) / n, 1),
            "fk_diff12": (round(12.0 * sum(e["fk"] - e["fd"] for e in w)
                                / rounds, 2) if rounds else None),
            "method_mix": ({k: round(methods.get(k, 0) / won_known, 4)
                            for k in ("elim", "boom", "defuse", "time")}
                           if won_known else None),
            "agents_top": [{"agent": a, "n": c}
                           for a, c in agents.most_common(5)],
        })
    teams.sort(key=lambda r: (-r["n_window"], -r["spread_avg"], r["name"]))
    return {
        "generated_at": now.isoformat(),
        "params": {"window_maps": config.TRENDS_WINDOW_MAPS,
                   "active_days": config.TRENDS_ACTIVE_DAYS,
                   "min_lifetime_maps": config.TRENDS_MIN_LIFETIME_MAPS},
        "n_teams": len(teams),
        "teams": teams,
    }
