"""Event-tier classification for vlr.gg event names.

Rules are keyword-based and deliberately simple so the mapping is auditable;
the evaluation report prints per-tier counts so misclassifications are visible
rather than hidden. Grounded in the event strings observed in the real scrape
(2026 naming):

- tier1          VCT 2026 international leagues (Americas/EMEA/Pacific/China),
                 Masters, Valorant Champions
- tier2          Challengers leagues; China Evolution Series (the Challengers-
                 equivalent path in China)
- game_changers  Game Changers circuit
- other          regional qualifiers, community cups, everything else

Event strings from the scraper can contain the series line glued on with
embedded newlines/tabs; normalize first.
"""
from __future__ import annotations

import re

TIER_ORDER = ["tier1", "tier2", "game_changers", "other"]

_WS = re.compile(r"\s+")
_VCT = re.compile(r"\bvct\b")


def normalize_event(event: str) -> str:
    return _WS.sub(" ", event or "").strip()


def classify_tier(event: str) -> str:
    e = normalize_event(event).lower()
    if "game changers" in e:
        return "game_changers"
    if "challengers" in e or "evolution series" in e:
        return "tier2"
    if _VCT.search(e) or "champions tour" in e or "masters" in e \
            or "valorant champions" in e:
        return "tier1"
    return "other"
