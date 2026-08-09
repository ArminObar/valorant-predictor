"""Roster-continuity features, Phase 1 (ASSUMPTIONS §66).

Owner-scoped: membership data only — WHO is on the lineup, computed from
team-map rows the store already holds. No player performance stats, no
new scraping, no parser changes; identity is the display name, which is
acceptable for map-COUNT features (a mislink biases a count, it cannot
poison a performance history) and is stated as a Phase-2 upgrade.

Two features per team, differenced A−B like everything else:

  roster_ext_maps_log   log1p of the current lineup's total prior maps
                        played on OTHER teams — imported experience,
                        the direct attack on the new-team cold start.
  roster_coplay_log     log1p of the mean pairwise co-appearance count
                        among the current lineup, any team — "have these
                        five actually played together".

The current lineup is the team's most recent ELIGIBLE map's lineup;
eligibility is the project rule: a map counts only once its estimated
finish precedes the cutoff (features/asof.estimated_end — same
constants, same direction of compromise as §3). A team with no eligible
map yet (a literal debut) has no lineup and both features are 0.0: the
debut match itself stays at defaults by design, stated in §66.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from itertools import combinations
from math import log1p

import pandas as pd

from .asof import add_est_end


def _events(maps_df: pd.DataFrame) -> list[tuple]:
    """(est_end_ts, team_key, lineup_tuple) per team-map row, sorted by
    estimated finish (ties by start then match id for determinism)."""
    df = add_est_end(maps_df)
    ev = []
    for r in df.itertuples(index=False):
        lineup = tuple(sorted(set(r.lineup or ())))
        ev.append((r.est_end_ts, r.start_ts, str(r.match_id),
                   r.team, lineup))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    return ev


class _State:
    """Running membership tallies over the event sweep."""

    def __init__(self) -> None:
        self.player_total: dict = defaultdict(int)
        self.player_team: dict = defaultdict(int)
        self.coplay: dict = defaultdict(int)
        self.last_lineup: dict = {}

    def apply(self, team: str, lineup: tuple) -> None:
        for p in lineup:
            self.player_total[p] += 1
            self.player_team[(p, team)] += 1
        for a, b in combinations(lineup, 2):
            self.coplay[(a, b)] += 1
        if lineup:
            self.last_lineup[team] = lineup

    def features(self, team: str) -> dict:
        lineup = self.last_lineup.get(team, ())
        if not lineup:
            return {"roster_ext_maps_log": 0.0, "roster_coplay_log": 0.0}
        ext = sum(max(self.player_total[p]
                      - self.player_team[(p, team)], 0) for p in lineup)
        if len(lineup) >= 2:
            pairs = list(combinations(lineup, 2))
            co = sum(self.coplay[pr] for pr in pairs) / len(pairs)
        else:
            co = 0.0
        return {"roster_ext_maps_log": log1p(float(ext)),
                "roster_coplay_log": log1p(float(co))}


def roster_continuity_table(maps_df: pd.DataFrame,
                            lites: list[dict]) -> dict:
    """Batch answers for training: {(match_id, team_key): features},
    computed in one chronological sweep so the whole build stays
    O(rows). Cutoff per match is its start_ts; events are admitted once
    est_end <= cutoff — the identical eligibility rule the rest of the
    feature build uses."""
    ev = _events(maps_df)
    order = sorted(range(len(lites)),
                   key=lambda i: (lites[i]["start_ts"],
                                  str(lites[i]["match_id"])))
    st = _State()
    out: dict = {}
    ptr = 0
    for i in order:
        lite = lites[i]
        cutoff = lite["start_ts"]
        while ptr < len(ev) and ev[ptr][0] <= cutoff:
            st.apply(ev[ptr][3], ev[ptr][4])
            ptr += 1
        for side in ("a", "b"):
            out[(str(lite["match_id"]), lite[side])] = \
                st.features(lite[side])
    return out


def roster_features_asof(maps_df: pd.DataFrame, team: str,
                         cutoff) -> dict:
    """Serving-path answer for one team at one cutoff. O(rows) per call
    — fine for a handful of upcoming matches; the training path uses the
    batch sweep. Pinned equal to the batch answer by test."""
    st = _State()
    for e in _events(maps_df):
        if e[0] > cutoff:
            break
        st.apply(e[3], e[4])
    return st.features(team)
