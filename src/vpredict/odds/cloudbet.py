"""Cloudbet Feed API source — the capture/de-vig correctness harness.

Wired FIRST per ASSUMPTIONS §13: an official, sanctioned API validates the
whole capture path before anything points at a book that doesn't want to be
read. Endpoints and shapes verified against Cloudbet's public docs
(sports-api.cloudbet.com/pub/v2/odds; X-API-Key header; sports ->
competitions -> events, each event carrying `markets` ->
`submarkets` -> `selections` with `outcome` home/away and decimal `price`).

The exact Valorant market key is NOT hard-coded: the docs' samples don't
show esports, so the client discovers any two-outcome home/away market whose
key looks like a series winner (contains "winner" or "moneyline"), logs
every market key it saw, and stores the raw responses — first live run on
the Mac pins the real key (LOG entry 25's protocol).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable

from .. import config
from .schema import OddsCapture, append_raw

log = logging.getLogger("vpredict.odds.cloudbet")

WINNER_KEY_HINTS = ("winner", "moneyline", "match_odds")


def _default_fetcher() -> Callable[[str], tuple[int, str]]:
    """(status, body) GET with the API key; requests imported lazily so
    fixture tests never need the network stack configured."""
    import requests

    key = os.environ.get("CLOUDBET_API_KEY")
    if not key:
        raise RuntimeError(
            "CLOUDBET_API_KEY is not set. Get a free Feed API key from your "
            "Cloudbet account (docs: https://www.cloudbet.com/api/) and "
            "export it before capturing.")
    sess = requests.Session()
    sess.headers.update({"X-API-Key": key, "Accept": "application/json"})
    last = [0.0]

    def fetch(url: str) -> tuple[int, str]:
        wait = config.ODDS_MIN_INTERVAL_S - (time.monotonic() - last[0])
        if wait > 0:
            time.sleep(wait)
        r = sess.get(url, timeout=20)
        last[0] = time.monotonic()
        append_raw("cloudbet", url, r.status_code, r.text)
        return r.status_code, r.text

    return fetch


def _get_json(fetch, url: str) -> dict | None:
    import json
    status, body = fetch(url)
    if status != 200:
        log.warning("cloudbet %s -> %s", url, status)
        return None
    try:
        return json.loads(body)
    except ValueError:
        log.warning("cloudbet %s -> non-JSON body", url)
        return None


def find_valorant_competition_keys(fetch=None) -> list[str]:
    """Discover competition keys under the esports sport whose name or key
    mentions valorant. Nothing is assumed about Cloudbet's naming beyond
    'esport' appearing in the sport key."""
    fetch = fetch or _default_fetcher()
    base = config.CLOUDBET_BASE_URL
    sports = _get_json(fetch, f"{base}/sports") or {}
    esport_keys = [s["key"] for s in sports.get("sports", [])
                   if "esport" in s.get("key", "").casefold()]
    if not esport_keys:
        log.warning("cloudbet: no esports sport key found among %s",
                    [s.get("key") for s in sports.get("sports", [])][:20])
    comps: list[str] = []
    for sk in esport_keys:
        detail = _get_json(fetch, f"{base}/sports/{sk}") or {}
        for cat in detail.get("categories", []):
            for comp in cat.get("competitions", []):
                blob = f"{comp.get('name', '')} {comp.get('key', '')}".casefold()
                if "valorant" in blob:
                    comps.append(comp["key"])
    return comps


def _winner_selections(markets: dict) -> tuple[str, float, float] | None:
    """Pick the series-winner market: any market whose key contains a winner
    hint and whose first submarket has exactly a home and an away BACK
    selection with no params (no handicap/total lines)."""
    for mkey, market in sorted((markets or {}).items()):
        if not any(h in mkey.casefold() for h in WINNER_KEY_HINTS):
            continue
        for sub in (market.get("submarkets") or {}).values():
            prices: dict[str, float] = {}
            for sel in sub.get("selections", []):
                if sel.get("params"):
                    continue
                if sel.get("side") not in (None, "BACK"):
                    continue
                if sel.get("outcome") in ("home", "away"):
                    prices[sel["outcome"]] = float(sel["price"])
            if set(prices) == {"home", "away"}:
                return mkey, prices["home"], prices["away"]
    return None


def parse_competition_events(payload: dict, captured_at: datetime,
                             capture_kind: str) -> tuple[list[OddsCapture],
                                                         list[str]]:
    """Raw competition payload -> unlinked captures + every market key seen
    (returned so the capture log can report what the book actually offers)."""
    out: list[OddsCapture] = []
    seen_keys: set[str] = set()
    for ev in payload.get("events", []):
        seen_keys.update((ev.get("markets") or {}).keys())
        home, away = ev.get("home") or {}, ev.get("away") or {}
        if not home.get("name") or not away.get("name"):
            continue                       # outright/award style event
        if ev.get("status") not in ("TRADING", "TRADING_LIVE", None):
            continue
        pick = _winner_selections(ev.get("markets") or {})
        if pick is None:
            continue
        mkey, p_home, p_away = pick
        start = ev.get("startTime") or ev.get("cutoffTime")
        out.append(OddsCapture(
            captured_at=captured_at, source="cloudbet",
            capture_kind=capture_kind,
            book_event_id=str(ev.get("id")),
            book_home=home["name"], book_away=away["name"],
            book_start_ts=start, book_market_key=mkey,
            price_home=p_home, price_away=p_away))
    return out, sorted(seen_keys)


def fetch_valorant_fixtures(captured_at: datetime, capture_kind: str,
                            fetch=None) -> list[OddsCapture]:
    fetch = fetch or _default_fetcher()
    base = config.CLOUDBET_BASE_URL
    captures: list[OddsCapture] = []
    all_keys: set[str] = set()
    for comp_key in find_valorant_competition_keys(fetch):
        payload = _get_json(fetch, f"{base}/competitions/{comp_key}")
        if not payload:
            continue
        got, keys = parse_competition_events(payload, captured_at,
                                             capture_kind)
        captures.extend(got)
        all_keys.update(keys)
    if all_keys:
        log.info("cloudbet market keys seen: %s", sorted(all_keys))
    return captures
