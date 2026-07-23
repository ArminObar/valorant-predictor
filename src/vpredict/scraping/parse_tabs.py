"""Tier B parsers: economy and performance tabs of a match page.

Everything here is optional by design. Any structural surprise returns None and
the caller drops the corresponding features (build-spec rule: never stall or
silently approximate Tier B).

Economy tab (?game={id}&tab=economy): `table.wf-table-inset.mod-econ`, one row
per team, cells like "14 (9)" = rounds of that buy type (won).
Performance tab (?game={id}&tab=performance): `table.wf-table-inset.mod-adv-stats`
with per-player 2K..5K, 1v1..1v5, ECON, PL, DE columns.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..data.schema import EconSummary

_PAIR = re.compile(r"(\d+)\s*\((\d+)\)")
_INT = re.compile(r"^\d+$")


def parse_econ_tab(html: str) -> tuple[EconSummary, EconSummary] | None:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.wf-table-inset.mod-econ")
    if table is None:
        return None
    headers = [th.get_text(strip=True).lower() for th in table.select("thead th")]
    body_rows = table.select("tbody tr")
    if len(body_rows) < 2 or not headers:
        return None

    def col_idx(*needles: str) -> int | None:
        for i, h in enumerate(headers):
            if all(n in h for n in needles):
                return i
        return None

    idx = {
        "pistol": col_idx("pistol"),
        "eco": col_idx("eco (won)") or col_idx("eco"),
        "semi_eco": col_idx("semi-eco"),
        "semi_buy": col_idx("semi-buy"),
        "full_buy": col_idx("full buy"),
    }

    def row_to_econ(tr) -> EconSummary | None:
        tds = tr.select("td")
        if len(tds) != len(headers):
            return None

        def pair(i: int | None):
            if i is None:
                return None
            m = _PAIR.search(tds[i].get_text(strip=True))
            return (int(m.group(1)), int(m.group(2))) if m else None

        pistol = None
        if idx["pistol"] is not None:
            t = tds[idx["pistol"]].get_text(strip=True)
            if _INT.match(t):
                pistol = int(t)
        return EconSummary(
            pistol_won=pistol,
            eco=pair(idx["eco"]),
            semi_eco=pair(idx["semi_eco"]),
            semi_buy=pair(idx["semi_buy"]),
            full_buy=pair(idx["full_buy"]),
        )

    e1, e2 = row_to_econ(body_rows[0]), row_to_econ(body_rows[1])
    if e1 is None or e2 is None:
        return None
    return e1, e2


def parse_performance_tab(html: str) -> dict[str, dict[str, int]] | None:
    """Return {player_name_lower: {multikills, clutch_wins, plants, defuses}}."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.wf-table-inset.mod-adv-stats")
    if table is None:
        return None
    headers = [th.get_text(strip=True).upper() for th in table.select("thead th")]
    if not headers:
        return None

    def cols(names: tuple[str, ...]) -> list[int]:
        return [i for i, h in enumerate(headers) if h in names]

    mk_cols = cols(("2K", "3K", "4K", "5K"))
    cl_cols = cols(("1V1", "1V2", "1V3", "1V4", "1V5"))
    pl_cols = cols(("PL", "PLANTS"))
    de_cols = cols(("DE", "DEFUSES"))
    if not mk_cols and not cl_cols:
        return None

    out: dict[str, dict[str, int]] = {}
    for tr in table.select("tbody tr"):
        tds = tr.select("td")
        if len(tds) != len(headers):
            continue
        name_el = tds[0].select_one(".text-of")
        name = (name_el.get_text(strip=True) if name_el
                else tds[0].get_text("\n", strip=True).split("\n")[0]).strip().lower()
        if not name:
            continue

        def total(ixs: list[int]) -> int:
            s = 0
            for i in ixs:
                t = tds[i].get_text(strip=True)
                if _INT.match(t):
                    s += int(t)
            return s

        out[name] = {
            "multikills": total(mk_cols),
            "clutch_wins": total(cl_cols),
            "plants": total(pl_cols),
            "defuses": total(de_cols),
        }
    return out or None
