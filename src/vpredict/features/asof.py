"""The as-of-date feature engine — the leakage guard lives here.

Contract: every statistic returned for a cutoff time T is computed ONLY from
map rows whose estimated finish time is <= T. Finish time is start_ts plus an
assumed duration by series length (vlr.gg exposes start times only); the
assumption is conservative and documented in ASSUMPTIONS.md.

This is an explicit as-of function, not a filter over a precomputed season
table: every call re-derives eligibility from raw rows, and tests/test_leakage.py
poisons the future to prove nothing leaks — including the league-mean priors
used for shrinkage, which are themselves computed as-of.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config


def estimated_end(start_ts: pd.Series, best_of: pd.Series) -> pd.Series:
    hours = best_of.map(config.ASSUMED_DURATION_HOURS).fillna(config.DEFAULT_DURATION_HOURS)
    return start_ts + pd.to_timedelta(hours, unit="h")


def add_est_end(maps_df: pd.DataFrame) -> pd.DataFrame:
    df = maps_df.copy()
    df["est_end_ts"] = estimated_end(df["start_ts"], df["best_of"])
    return df


def shrunk_rate(w_success: float, w_total: float, prior: float, m: float) -> float:
    """Empirical-Bayes shrinkage: pull a weighted rate toward `prior` with the
    strength of `m` pseudo-observations. With no data, returns the prior."""
    return (w_success + m * prior) / (w_total + m) if (w_total + m) > 0 else prior


@dataclass
class TeamSnapshot:
    n_maps: int = 0
    round_share: float = 0.5
    atk_eff: float = 0.5
    def_eff: float = 0.5
    fk_diff12: float = 0.0
    pistol_wr: float = 0.5
    rest_days: float = 30.0
    roster_stability: float = 1.0
    # Tier B (None when unavailable)
    fullbuy_wr: float | None = None
    lowbuy_wr: float | None = None
    clutch_per_map: float | None = None
    multikill_per_map: float | None = None
    extras: dict = field(default_factory=dict)


class AsOfEngine:
    """Computes leak-free team statistics at an arbitrary cutoff time."""

    def __init__(
        self,
        maps_df: pd.DataFrame,
        half_life_days: float = config.DEFAULT_HALF_LIFE_DAYS,
        roster_factor: float = config.DEFAULT_ROSTER_FACTOR,
        shrink_m_rounds: float = config.SHRINK_M_ROUNDS,
        shrink_m_pistols: float = config.SHRINK_M_PISTOLS,
    ) -> None:
        if maps_df.empty:
            raise ValueError("AsOfEngine needs a non-empty maps frame")
        df = add_est_end(maps_df)
        df = df.sort_values("est_end_ts", kind="stable").reset_index(drop=True)
        self.df = df
        self.half_life_days = float(half_life_days)
        self.roster_factor = float(roster_factor)
        self.m_rounds = float(shrink_m_rounds)
        self.m_pistols = float(shrink_m_pistols)
        self._by_team: dict[str, pd.DataFrame] = {
            t: g.reset_index(drop=True) for t, g in df.groupby("team", sort=False)
        }
        # Global cumulative sums over est_end order, for O(log n) as-of league priors.
        g = df
        self._g_end = g["est_end_ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
        atk_rounds = (g["atk_rw"].fillna(0) + g["atk_rl"].fillna(0)).to_numpy(float)
        self._cum = {
            "atk_rw": np.cumsum(g["atk_rw"].fillna(0).to_numpy(float)),
            "atk_n": np.cumsum(atk_rounds),
            "fullbuy_w": np.cumsum(g["fullbuy_w"].fillna(0).to_numpy(float)),
            "fullbuy_n": np.cumsum(g["fullbuy_n"].fillna(0).to_numpy(float)),
            "lowbuy_w": np.cumsum(g["lowbuy_w"].fillna(0).to_numpy(float)),
            "lowbuy_n": np.cumsum(g["lowbuy_n"].fillna(0).to_numpy(float)),
            "clutch": np.cumsum(g["clutch_wins"].fillna(0).to_numpy(float)),
            "mk": np.cumsum(g["multikills"].fillna(0).to_numpy(float)),
            "maps": np.cumsum(np.ones(len(g))),
            "mk_maps": np.cumsum(g["multikills"].notna().to_numpy(float)),
            "clutch_maps": np.cumsum(g["clutch_wins"].notna().to_numpy(float)),
        }

    # ---------------------------------------------------------------- priors
    def _cum_at(self, key: str, cutoff: pd.Timestamp) -> float:
        i = int(np.searchsorted(self._g_end, np.datetime64(cutoff.tz_convert("UTC").tz_localize(None)), side="right"))
        return float(self._cum[key][i - 1]) if i > 0 else 0.0

    def league_priors(self, cutoff: pd.Timestamp) -> dict[str, float]:
        atk_n = self._cum_at("atk_n", cutoff)
        atk_mean = self._cum_at("atk_rw", cutoff) / atk_n if atk_n > 0 else 0.5
        fb_n = self._cum_at("fullbuy_n", cutoff)
        lb_n = self._cum_at("lowbuy_n", cutoff)
        mk_maps = self._cum_at("mk_maps", cutoff)
        cl_maps = self._cum_at("clutch_maps", cutoff)
        return {
            "atk_eff": atk_mean,
            "def_eff": 1.0 - atk_mean,  # every attack round is someone's defense round
            "fullbuy_wr": self._cum_at("fullbuy_w", cutoff) / fb_n if fb_n > 0 else 0.5,
            "lowbuy_wr": self._cum_at("lowbuy_w", cutoff) / lb_n if lb_n > 0 else 0.15,
            "clutch_per_map": self._cum_at("clutch", cutoff) / cl_maps if cl_maps > 0 else 0.0,
            "multikill_per_map": self._cum_at("mk", cutoff) / mk_maps if mk_maps > 0 else 0.0,
        }

    # ---------------------------------------------------------------- core
    def eligible(self, team: str, cutoff: pd.Timestamp, map_name: str | None = None) -> pd.DataFrame:
        g = self._by_team.get(team)
        if g is None:
            return self.df.iloc[0:0]
        g = g[g["est_end_ts"] <= cutoff]
        if map_name is not None:
            g = g[g["map_name"] == map_name]
        return g

    def _weights(self, g: pd.DataFrame, cutoff: pd.Timestamp) -> np.ndarray:
        age_days = (cutoff - g["start_ts"]).dt.total_seconds().to_numpy() / 86400.0
        w = 0.5 ** (np.maximum(age_days, 0.0) / self.half_life_days)
        if self.roster_factor < 1.0 and len(g) > 0:
            core = self._core_roster(g)
            if core:
                changed = g["lineup"].map(
                    lambda lu: 0 if not lu else max(0, 5 - len(set(lu) & core))
                ).to_numpy(float)
                w = w * (self.roster_factor ** changed)
        return w

    @staticmethod
    def _core_roster(g: pd.DataFrame) -> set[str]:
        recent = [lu for lu in g["lineup"].tail(5) if lu]
        if not recent:
            return set()
        counts: dict[str, int] = {}
        for lu in recent:
            for p in lu:
                counts[p] = counts.get(p, 0) + 1
        return set(sorted(counts, key=lambda p: (-counts[p], p))[:5])

    def team_snapshot(self, team: str, cutoff: pd.Timestamp,
                      map_name: str | None = None) -> TeamSnapshot:
        g = self.eligible(team, cutoff, map_name)
        snap = TeamSnapshot(n_maps=len(g))
        if len(g) == 0:
            return snap
        pri = self.league_priors(cutoff)
        w = self._weights(g, cutoff)

        rw = g["rounds_won"].to_numpy(float)
        rl = g["rounds_lost"].to_numpy(float)
        snap.round_share = shrunk_rate(float(w @ rw), float(w @ (rw + rl)), 0.5, self.m_rounds)

        atk_ok = g["atk_rw"].notna() & g["atk_rl"].notna()
        if atk_ok.any():
            wa = w[atk_ok.to_numpy()]
            arw = g.loc[atk_ok, "atk_rw"].to_numpy(float)
            arl = g.loc[atk_ok, "atk_rl"].to_numpy(float)
            drw = g.loc[atk_ok, "def_rw"].to_numpy(float)
            drl = g.loc[atk_ok, "def_rl"].to_numpy(float)
            snap.atk_eff = shrunk_rate(float(wa @ arw), float(wa @ (arw + arl)),
                                       pri["atk_eff"], self.m_rounds / 2)
            snap.def_eff = shrunk_rate(float(wa @ drw), float(wa @ (drw + drl)),
                                       pri["def_eff"], self.m_rounds / 2)

        fk_ok = g["fk"].notna() & g["fd"].notna()
        if fk_ok.any():
            wf = w[fk_ok.to_numpy()]
            fk = g.loc[fk_ok, "fk"].to_numpy(float)
            fd = g.loc[fk_ok, "fd"].to_numpy(float)
            rounds = (g.loc[fk_ok, "rounds_won"] + g.loc[fk_ok, "rounds_lost"]).to_numpy(float)
            tot = float(wf @ rounds)
            if tot > 0:
                # shrink toward the symmetric prior of 0 via pseudo-rounds
                snap.fk_diff12 = float(wf @ (fk - fd)) / (tot + self.m_rounds) * 12.0

        pw = g["pistols_won"].to_numpy(float)
        pp = g["pistols_played"].to_numpy(float)
        snap.pistol_wr = shrunk_rate(float(w @ pw), float(w @ pp), 0.5, self.m_pistols)

        last_start = g["start_ts"].max()
        snap.rest_days = float(min((cutoff - last_start).total_seconds() / 86400.0, 30.0))

        core = self._core_roster(g)
        recent = [lu for lu in g["lineup"].tail(5) if lu]
        if core and recent:
            snap.roster_stability = float(
                np.mean([len(set(lu) & core) / 5.0 for lu in recent]))

        # ---- Tier B (only when the data actually exists for this team)
        fb_ok = g["fullbuy_n"].notna()
        if fb_ok.any():
            wb = w[fb_ok.to_numpy()]
            n = g.loc[fb_ok, "fullbuy_n"].to_numpy(float)
            s = g.loc[fb_ok, "fullbuy_w"].to_numpy(float)
            snap.fullbuy_wr = shrunk_rate(float(wb @ s), float(wb @ n),
                                          pri["fullbuy_wr"], self.m_rounds / 2)
        lb_ok = g["lowbuy_n"].notna()
        if lb_ok.any():
            wb = w[lb_ok.to_numpy()]
            n = g.loc[lb_ok, "lowbuy_n"].to_numpy(float)
            s = g.loc[lb_ok, "lowbuy_w"].to_numpy(float)
            snap.lowbuy_wr = shrunk_rate(float(wb @ s), float(wb @ n),
                                         pri["lowbuy_wr"], self.m_rounds / 2)
        cl_ok = g["clutch_wins"].notna()
        if cl_ok.any():
            wc = w[cl_ok.to_numpy()]
            snap.clutch_per_map = shrunk_rate(
                float(wc @ g.loc[cl_ok, "clutch_wins"].to_numpy(float)),
                float(wc.sum()), pri["clutch_per_map"], 5.0)
        mk_ok = g["multikills"].notna()
        if mk_ok.any():
            wm = w[mk_ok.to_numpy()]
            snap.multikill_per_map = shrunk_rate(
                float(wm @ g.loc[mk_ok, "multikills"].to_numpy(float)),
                float(wm.sum()), pri["multikill_per_map"], 5.0)
        return snap


def snapshot_diffs(a: TeamSnapshot, b: TeamSnapshot) -> dict[str, float | None]:
    def d(x, y):
        return None if (x is None or y is None) else x - y
    return {
        "round_share_diff": a.round_share - b.round_share,
        "atk_eff_diff": a.atk_eff - b.atk_eff,
        "def_eff_diff": a.def_eff - b.def_eff,
        "fk_diff12_diff": a.fk_diff12 - b.fk_diff12,
        "pistol_wr_diff": a.pistol_wr - b.pistol_wr,
        "rest_diff": math.log1p(a.rest_days) - math.log1p(b.rest_days),
        "roster_stability_diff": a.roster_stability - b.roster_stability,
        "fullbuy_wr_diff": d(a.fullbuy_wr, b.fullbuy_wr),
        "lowbuy_wr_diff": d(a.lowbuy_wr, b.lowbuy_wr),
        "clutch_per_map_diff": d(a.clutch_per_map, b.clutch_per_map),
        "multikill_per_map_diff": d(a.multikill_per_map, b.multikill_per_map),
    }


TIER_A_DIFFS = ["round_share_diff", "atk_eff_diff", "def_eff_diff", "fk_diff12_diff",
                "pistol_wr_diff", "rest_diff", "roster_stability_diff"]
TIER_B_DIFFS = ["fullbuy_wr_diff", "lowbuy_wr_diff", "clutch_per_map_diff",
                "multikill_per_map_diff"]
