"""Fuzzy book-name -> vlr-name matching: SUGGESTIONS, never silent links.

The capture path stays conservative (exact normalized match, then the alias
table — schema.link_fixture). This module exists for the human step:
propose likely pairings for UNLINKED fixtures so confirmed pairs land in
aliases.json instead of being hand-typed every week.

Scoring is built around how books actually shorten org names
(field-observed on the first Cloudbet run, LOG entry 30):
  "Secret"  for "Team Secret"          -> generic-token drop, exact core
  "Titan"   for "Wuxi Titan Esports Club" -> token subset
  "G2"      for "G2 Esports"           -> generic-token drop
  "RRQ"     for "Rex Regum Qeon"       -> acronym of the full name

Two safety properties:
  * PROTECTED tokens (academy / GC / youth-style roster qualifiers) present
    on one side but not the other zero the score — "G2" must never suggest
    "G2 Academy", whatever the string similarity says.
  * An ambiguous top pair (runner-up within a margin) is flagged so the CLI
    forces an explicit pick instead of a default-yes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

# Organization furniture that books drop freely. Removing these never merges
# two different rosters.
GENERIC = {"esports", "esport", "gaming", "team", "club", "org", "the", "fc",
           "gg", "e", "sports"}
# Roster qualifiers that DO distinguish teams sharing an org name. A mismatch
# on any of these is disqualifying, not merely penalized.
PROTECTED = {"academy", "gc", "female", "fe", "youth", "black", "white",
             "red", "blue"}

_SPLIT = re.compile(r"[^a-z0-9]+")


def tokens(name: str) -> list[str]:
    return [t for t in _SPLIT.split((name or "").casefold()) if t]


def core_tokens(name: str) -> list[str]:
    kept = [t for t in tokens(name) if t not in GENERIC]
    return kept or tokens(name)          # never reduce a name to nothing


def _initials(toks: list[str]) -> str:
    return "".join(t[0] for t in toks)


def similarity(book_name: str, vlr_name: str) -> float:
    """0..1. Symmetric in spirit; the argument names only document intent."""
    raw_a, raw_b = tokens(book_name), tokens(vlr_name)
    a, b = core_tokens(book_name), core_tokens(vlr_name)
    if not a or not b:
        return 0.0
    if (PROTECTED & set(raw_a)) != (PROTECTED & set(raw_b)):
        return 0.0                        # sibling-roster guard
    if a == b:
        return 1.0
    sa, sb = set(a), set(b)
    if sa <= sb or sb <= sa:
        return 0.92
    if len(a) == 1 and a[0] in (_initials(raw_b), _initials(b)):
        return 0.90                       # acronym: RRQ / TS / DFM style
    if len(b) == 1 and b[0] in (_initials(raw_a), _initials(a)):
        return 0.90
    return SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()


@dataclass
class Suggestion:
    prediction: dict                      # the /api/upcoming row suggested
    score: float                          # min of the two team scores
    book_home_is_team1: bool
    team_scores: tuple[float, float]      # (book_home side, book_away side)
    ambiguous_with: dict | None = None    # runner-up prediction, if too close


def score_pair(book_home: str, book_away: str,
               prediction: dict) -> tuple[float, bool, tuple[float, float]]:
    """Best orientation for one fixture against one prediction row."""
    t1, t2 = prediction["team1_name"], prediction["team2_name"]
    straight = (similarity(book_home, t1), similarity(book_away, t2))
    flipped = (similarity(book_home, t2), similarity(book_away, t1))
    if min(straight) >= min(flipped):
        return min(straight), True, straight
    return min(flipped), False, flipped


def suggest(book_home: str, book_away: str, predictions: list[dict],
            threshold: float = 0.75,
            ambiguity_margin: float = 0.05) -> Suggestion | None:
    """The single best pairing for a fixture, or None below the threshold.
    A runner-up within `ambiguity_margin` is attached so callers can refuse
    to default-accept."""
    scored = []
    for p in predictions:
        s, orient, per_team = score_pair(book_home, book_away, p)
        scored.append((s, orient, per_team, p))
    scored.sort(key=lambda t: -t[0])
    if not scored or scored[0][0] < threshold:
        return None
    s, orient, per_team, p = scored[0]
    runner = None
    if (len(scored) > 1 and scored[1][0] >= threshold
            and s - scored[1][0] < ambiguity_margin
            and scored[1][3]["match_id"] != p["match_id"]):
        runner = scored[1][3]
    return Suggestion(prediction=p, score=s, book_home_is_team1=orient,
                      team_scores=per_team, ambiguous_with=runner)
