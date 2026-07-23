"""Typed schema for everything the scraper stores.

One `Match` per vlr.gg match page. Tier A fields are expected to parse on every
completed match; Tier B fields default to None/empty and the pipeline treats
them as optional everywhere downstream.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class PlayerMapStats(BaseModel):
    name: str
    agent: str = ""
    acs: Optional[float] = None
    kills: Optional[int] = None
    deaths: Optional[int] = None
    assists: Optional[int] = None
    kast_pct: Optional[float] = None
    adr: Optional[float] = None
    hs_pct: Optional[float] = None
    fk: Optional[int] = None
    fd: Optional[int] = None
    # Tier B (performance tab)
    multikills: Optional[int] = None      # rounds with 2+ kills (2K+3K+4K+5K)
    clutch_wins: Optional[int] = None     # 1v1..1v5 won
    plants: Optional[int] = None
    defuses: Optional[int] = None


class RoundResult(BaseModel):
    number: int
    winner: Literal["team1", "team2", ""] = ""
    side: Literal["attack", "defense", ""] = ""   # side of the WINNING team
    win_method: Literal["elim", "boom", "defuse", "time", ""] = ""


class EconSummary(BaseModel):
    """Per-team economy aggregates from the economy tab (Tier B).

    Each pair is (rounds_of_type, rounds_of_type_won), parsed from cells like
    '14 (9)'.
    """
    pistol_won: Optional[int] = None
    eco: Optional[tuple[int, int]] = None
    semi_eco: Optional[tuple[int, int]] = None
    semi_buy: Optional[tuple[int, int]] = None
    full_buy: Optional[tuple[int, int]] = None


class MapResult(BaseModel):
    game_id: str
    map_name: str
    index: int
    team1_score: int
    team2_score: int
    # Regulation side splits. OT rounds are counted in the totals above but not
    # attributed to a side (see ASSUMPTIONS.md).
    team1_ct: Optional[int] = None
    team1_t: Optional[int] = None
    team2_ct: Optional[int] = None
    team2_t: Optional[int] = None
    duration: str = ""
    rounds: list[RoundResult] = Field(default_factory=list)
    team1_players: list[PlayerMapStats] = Field(default_factory=list)
    team2_players: list[PlayerMapStats] = Field(default_factory=list)
    team1_econ: Optional[EconSummary] = None
    team2_econ: Optional[EconSummary] = None


class Match(BaseModel):
    match_id: str
    url: str = ""
    start_ts: datetime                      # UTC, from data-utc-ts
    status: Literal["completed", "upcoming", "live", "unknown"] = "unknown"
    best_of: int = 3
    event: str = ""
    series: str = ""                        # e.g. "Playoffs: Grand Final"
    patch: str = ""
    team1_id: str = ""
    team1_name: str = ""
    team2_id: str = ""
    team2_name: str = ""
    team1_maps: Optional[int] = None        # series score
    team2_maps: Optional[int] = None
    winner: Literal["team1", "team2", ""] = ""
    maps: list[MapResult] = Field(default_factory=list)
    veto_raw: str = ""                      # raw pick/ban note text if present
    scraped_at: Optional[datetime] = None
    synthetic: bool = False                 # True only for demo/simulated data

    def key_team(self, which: Literal["team1", "team2"]) -> str:
        """Stable team key: id when known, else normalized name."""
        tid = self.team1_id if which == "team1" else self.team2_id
        name = self.team1_name if which == "team1" else self.team2_name
        return tid or name.strip().lower()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
