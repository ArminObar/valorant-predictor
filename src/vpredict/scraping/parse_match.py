"""Parse a vlr.gg match page into a `Match`.

Selector knowledge is grounded in two actively maintained open-source scrapers
(axsddlr/vlrggapi, MIT; akhilnarang/vlrgg-scraper) inspected in July 2026 —
credited in the README. All code here is original.

Tier A extracted here: UTC start time (data-utc-ts), teams + ids, event/series,
best-of, per-map scores with CT/T splits, round-by-round winner/side/method
(gives pistols for free), and per-player per-map stats. VLR currently renders
player stats as `.ovw-cell` divs keyed by data-col; the legacy
`table.wf-table-inset.mod-overview` layout is kept as a fallback.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup, Tag

from ..data.schema import Match, MapResult, PlayerMapStats, RoundResult

_HREF_ID = re.compile(r"^/(?:team/)?(\d+)/")


# --------------------------------------------------------------------------- helpers
def _txt(el) -> str:
    return el.get_text(strip=True) if el else ""


def _num(s: str, cast=float):
    s = (s or "").replace("%", "").replace("+", "").strip()
    if s in ("", "-", "–", "—", "/"):
        return None
    try:
        return cast(s)
    except ValueError:
        return None


def _parse_utc_ts(soup: BeautifulSoup) -> datetime | None:
    el = soup.select_one(".moment-tz-convert[data-utc-ts]")
    if el:
        raw = el.get("data-utc-ts", "").strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


# --------------------------------------------------------------------------- header
def _parse_header(soup: BeautifulSoup, out: dict) -> None:
    sup = soup.select_one(".match-header-super")
    if sup:
        a = sup.select_one("a")
        first_div = sup.select_one("div")
        out["event"] = _txt(a.select_one("div") or a) if a else _txt(first_div)
        out["series"] = _txt(sup.select_one(".match-header-event-series"))

    note = soup.select_one(".match-header-note")
    out["veto_raw"] = _txt(note)

    status = _txt(soup.select_one(".match-header-vs-note")).lower()
    if "final" in status:
        out["status"] = "completed"
    elif "live" in status:
        out["status"] = "live"
    elif status:
        out["status"] = "upcoming"

    for which, mod in (("team1", "mod-1"), ("team2", "mod-2")):
        link = soup.select_one(f".match-header-link.{mod}")
        if link:
            m = _HREF_ID.match(link.get("href", "") or "")
            if m:
                out[f"{which}_id"] = m.group(1)
        name_el = soup.select_one(f".match-header-link-name.{mod} .wf-title-med") or \
            soup.select_one(f".match-header-link-name.{mod}")
        raw = name_el.get_text("\n", strip=True) if name_el else ""
        out[f"{which}_name"] = raw.split("\n")[0].strip()

    spans = soup.select(".match-header-vs-score span")
    digits = [(s.get("class") or [], s.get_text(strip=True)) for s in spans
              if s.get_text(strip=True).isdigit()]
    if len(digits) >= 2:
        out["team1_maps"] = int(digits[0][1])
        out["team2_maps"] = int(digits[1][1])
        if "match-header-vs-score-winner" in digits[0][0]:
            out["winner"] = "team1"
        elif "match-header-vs-score-winner" in digits[1][0]:
            out["winner"] = "team2"
        elif out.get("status") == "completed":
            out["winner"] = "team1" if out["team1_maps"] > out["team2_maps"] else "team2"


def _infer_best_of(soup: BeautifulSoup, out: dict) -> int:
    for el in soup.select(".match-header-vs-note"):
        m = re.search(r"bo\s*([135])", el.get_text(strip=True).lower())
        if m:
            return int(m.group(1))
    t1, t2 = out.get("team1_maps"), out.get("team2_maps")
    if t1 is not None and t2 is not None:
        wins = max(t1, t2)
        if wins >= 3:
            return 5
        if wins == 2 or (t1 + t2) >= 2:
            return 3
        if t1 + t2 == 1:
            return 1
    return 3


# --------------------------------------------------------------------------- maps
def _side_scores(block: Tag) -> tuple[int | None, int | None]:
    """(ct, t) regulation wins for one .team block in a map header."""
    def pick(cls: str) -> int | None:
        for el in block.select(f".{cls}"):
            v = _num(el.get_text(strip=True), int)
            if v is not None:
                return v
        return None
    return pick("mod-ct"), pick("mod-t")


def _parse_rounds(game: Tag) -> list[RoundResult]:
    rounds: list[RoundResult] = []
    cont = game.select_one(".vlr-rounds")
    if not cont:
        return rounds
    n = 0
    for col in cont.select(".vlr-rounds-row-col"):
        cls = col.get("class") or []
        if "mod-spacing" in cls:
            continue
        sqs = col.select(".rnd-sq")
        if not sqs:
            continue
        num_el = col.select_one(".rnd-num")
        n = _num(_txt(num_el), int) or (n + 1)
        winner, side, method = "", "", ""
        for idx, sq in enumerate(sqs):
            sq_cls = sq.get("class") or []
            if "mod-win" in sq_cls:
                winner = "team1" if idx == 0 else "team2"
                if "mod-t" in sq_cls:
                    side = "attack"
                elif "mod-ct" in sq_cls:
                    side = "defense"
                img = sq.select_one("img")
                if img and img.get("src"):
                    stem = img["src"].rsplit("/", 1)[-1].split(".")[0]
                    if stem in ("elim", "boom", "defuse", "time"):
                        method = stem
                break
        rounds.append(RoundResult(number=int(n), winner=winner, side=side, win_method=method))
    return rounds


_OVW_COLS = ("rating2", "acs", "kd-diff", "kast", "adr", "hsp", "fb", "fd", "fk-diff")


def _parse_players_ovw(game: Tag) -> tuple[list[PlayerMapStats], list[PlayerMapStats]]:
    cells = game.select(".ovw-cell")
    player_cells = [c for c in cells if "mod-player" in (c.get("class") or [])]
    stat_cells = [c for c in cells if "mod-player" not in (c.get("class") or [])]
    if len(player_cells) < 2:
        return [], []
    per = len(stat_cells) // len(player_cells)

    def one(pcell: Tag, group: list[Tag]) -> PlayerMapStats:
        name = _txt(pcell.select_one(".ovw-player-name")) or _txt(pcell.select_one(".text-of"))
        agent = ""
        img = pcell.select_one(".ovw-agents img")
        if img:
            agent = img.get("title") or img.get("alt") or ""
        vals: dict[str, str] = {}
        kills = deaths = assists = None
        for c in group:
            if "mod-kda" in (c.get("class") or []):
                for ks in c.select(".ovw-kda-stat"):
                    v = _txt(ks.select_one(".side.mod-both")) or _txt(ks)
                    col = ks.get("data-col", "")
                    if col == "kills":
                        kills = _num(v, int)
                    elif col == "deaths":
                        deaths = _num(v, int)
                    elif col == "assists":
                        assists = _num(v, int)
                continue
            col = c.get("data-col", "")
            if col:
                vals[col] = _txt(c.select_one(".side.mod-both")) or _txt(c)
        return PlayerMapStats(
            name=name, agent=agent,
            acs=_num(vals.get("acs", "")), kills=kills, deaths=deaths, assists=assists,
            kast_pct=_num(vals.get("kast", "")), adr=_num(vals.get("adr", "")),
            hs_pct=_num(vals.get("hsp", "")),
            fk=_num(vals.get("fb", ""), int), fd=_num(vals.get("fd", ""), int),
        )

    players = [one(pc, stat_cells[i * per:(i + 1) * per]) for i, pc in enumerate(player_cells)]
    half = len(players) // 2
    return players[:half], players[half:]


def _parse_players_legacy(game: Tag) -> tuple[list[PlayerMapStats], list[PlayerMapStats]]:
    tables = game.select("table.wf-table-inset.mod-overview")

    def cell_val(td: Tag) -> str:
        both = td.select_one(".side.mod-both")
        return _txt(both) if both else _txt(td)

    def rows(table: Tag) -> list[PlayerMapStats]:
        out = []
        for tr in table.select("tbody tr"):
            tds = tr.select("td")
            if len(tds) < 12:
                continue
            name = _txt(tds[0].select_one(".text-of")) or _txt(tds[0])
            img = tds[1].select_one("img")
            agent = (img.get("title") or img.get("alt") or "") if img else ""
            v = [cell_val(td) for td in tds]
            out.append(PlayerMapStats(
                name=name, agent=agent,
                acs=_num(v[3]), kills=_num(v[4], int), deaths=_num(v[5], int),
                assists=_num(v[6], int), kast_pct=_num(v[8]), adr=_num(v[9]),
                hs_pct=_num(v[10]),
                fk=_num(v[11], int) if len(v) > 11 else None,
                fd=_num(v[12], int) if len(v) > 12 else None,
            ))
        return out

    t1 = rows(tables[0]) if len(tables) > 0 else []
    t2 = rows(tables[1]) if len(tables) > 1 else []
    return t1, t2


_MAP_TIME = re.compile(r"\s*\d{1,2}:\d{2}(?::\d{2})?\s*$")
_LABEL_TOKENS = {"PICK", "BAN", "DECIDER"}
_LABEL_SUFFIX = re.compile(r"(?:PICK|BAN|DECIDER)\s*$")   # uppercase only: never mangles a real map name
_TIME_ONLY = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


def _own_text(el: Tag) -> str:
    """Direct text of an element, EXCLUDING nested tags.

    vlr.gg renders the veto label as a child span inside the map-name span
    (`<span>Lotus<span class="picked">PICK</span></span>`), so get_text() on the
    name span yields "LotusPICK". Field-found bug: that concatenation fragments
    per-map history into two keys ("Lotus" for deciders, "LotusPICK" for picks).
    """
    return "".join(s for s in el.find_all(string=True, recursive=False)).strip()


def _parse_maps(soup: BeautifulSoup) -> list[MapResult]:
    maps: list[MapResult] = []
    idx = 0
    for game in soup.select("div.vm-stats-game"):
        gid = game.get("data-game-id", "")
        if gid == "all" or not gid:
            continue
        header = game.select_one(".vm-stats-game-header")
        if header is None:
            continue
        map_el = header.select_one(".map")
        map_name = ""
        if map_el:
            for span in map_el.select("span"):
                own = _own_text(span)
                if not own or own.upper() in _LABEL_TOKENS or _TIME_ONLY.match(own):
                    continue
                map_name = own
                break
            if not map_name:
                map_name = _MAP_TIME.sub("", map_el.get_text("\n", strip=True).split("\n")[0]).strip()
            map_name = _LABEL_SUFFIX.sub("", map_name).strip()
        teams = header.select(".team")
        if len(teams) < 2:
            continue
        s1 = _num(_txt(teams[0].select_one(".score")), int)
        s2 = _num(_txt(teams[1].select_one(".score")), int)
        if s1 is None or s2 is None:
            continue
        ct1, t1 = _side_scores(teams[0])
        ct2, t2 = _side_scores(teams[1])
        p1, p2 = _parse_players_ovw(game)
        if not p1 and not p2:
            p1, p2 = _parse_players_legacy(game)
        idx += 1
        maps.append(MapResult(
            game_id=str(gid), map_name=map_name, index=idx,
            team1_score=int(s1), team2_score=int(s2),
            team1_ct=ct1, team1_t=t1, team2_ct=ct2, team2_t=t2,
            duration=_txt(game.select_one(".map-duration")),
            rounds=_parse_rounds(game),
            team1_players=p1, team2_players=p2,
        ))
    return maps


# --------------------------------------------------------------------------- entry
def parse_match_page(html: str, match_id: str, url: str = "") -> Match:
    soup = BeautifulSoup(html, "lxml")
    out: dict = {"match_id": match_id, "url": url, "status": "unknown"}
    _parse_header(soup, out)
    start_ts = _parse_utc_ts(soup)
    if start_ts is None:
        raise ValueError(f"match {match_id}: no data-utc-ts found — page layout changed?")
    out["start_ts"] = start_ts
    out["best_of"] = _infer_best_of(soup, out)
    if out.get("status") == "completed":
        out["maps"] = _parse_maps(soup)
    return Match(**out)
