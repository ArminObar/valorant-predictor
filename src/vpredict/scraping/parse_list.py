"""Parse vlr.gg listing pages (/matches and /matches/results).

Listing cards only provide match ids reliably (dates on listings are rendered
in a viewer-local timezone). The authoritative UTC start time is taken from the
match page itself (data-utc-ts), so the crawler treats listings purely as an id
discovery mechanism.

Selectors verified against a real vlr.gg results snapshot (July 2026 layout):
cards are `a.wf-module-item.match-item`, grouped under `div.wf-label` date
headers; status lives in `.ml-status`; team names in `.match-item-vs-team-name`
/ `.text-of`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_HREF_ID = re.compile(r"^/(\d+)/")


@dataclass
class ListedMatch:
    match_id: str
    href: str
    status: str          # "completed" | "upcoming" | "live" | "unknown"
    team1: str
    team2: str
    event: str


def parse_listing(html: str) -> list[ListedMatch]:
    soup = BeautifulSoup(html, "lxml")
    out: list[ListedMatch] = []
    for a in soup.select("a.wf-module-item.match-item"):
        href = a.get("href", "") or ""
        m = _HREF_ID.match(href)
        if not m:
            continue
        status_el = a.select_one(".ml-status")
        raw_status = status_el.get_text(strip=True).lower() if status_el else ""
        if raw_status in ("completed", "final"):
            status = "completed"
        elif raw_status == "live":
            status = "live"
        elif raw_status == "upcoming" or re.match(r"^\d+[smhd]", raw_status):
            status = "upcoming"
        else:
            status = "unknown"

        names = [t.get_text(strip=True) for t in a.select(".match-item-vs-team-name .text-of")]
        if len(names) < 2:
            names = [t.get_text(strip=True) for t in a.select(".text-of")][:2]
        event_el = a.select_one(".match-item-event")
        event = ""
        if event_el:
            event = event_el.get_text("\n", strip=True).split("\n")[-1].strip()

        out.append(ListedMatch(
            match_id=m.group(1),
            href=href,
            status=status,
            team1=names[0] if len(names) > 0 else "",
            team2=names[1] if len(names) > 1 else "",
            event=event,
        ))
    return out
