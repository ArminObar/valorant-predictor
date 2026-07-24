"""Pinnacle source — Playwright, response interception, Mac-only.

Design per ASSUMPTIONS §13/§14: a real browser loads Pinnacle's Valorant
matchups page and we harvest the JSON the page fetches for ITSELF (network
response interception) rather than scraping the DOM — the app's own API
payloads are far more stable than its markup. The candidate URL substrings
and field names below come from the guest API the site is known to use;
they are UNVALIDATED until the first live run on the Mac (same protocol as
the vlr scraper's first run, LOG entries 9/25). `--debug` dumps every
intercepted JSON response to disk so a mismatch is a one-paste fix.

Never run headless-hostile tricks: one page load, no parallelism, and the
raw responses are appended to the odds raw log for auditability.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .. import config
from .schema import OddsCapture, append_raw

log = logging.getLogger("vpredict.odds.pinnacle")

MATCHUPS_URL = "https://www.pinnacle.com/en/esports/games/valorant/matchups/"
# Substrings identifying the page's own data calls (guest API):
INTERCEPT_HINTS = ("matchups", "markets")


def american_to_decimal(american: float) -> float:
    a = float(american)
    if a >= 100:
        return 1.0 + a / 100.0
    if a <= -100:
        return 1.0 + 100.0 / (-a)
    raise ValueError(f"not an american price: {american}")


def _price_to_decimal(value: float) -> float:
    """Pinnacle's guest API serves american prices; tolerate decimal too
    (anything in (1, 100) that isn't american-shaped)."""
    v = float(value)
    if -99.0 < v < 100.0 and v > 1.0:
        return v
    return american_to_decimal(v)


def harvest_page_json(debug_dir: Path | None = None) -> list[dict]:
    """Load the matchups page once and return every intercepted JSON body
    whose URL mentions an INTERCEPT_HINT. Requires `pip install playwright`
    and `playwright install chromium` (Mac setup in the runbook)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:                               # pragma: no cover
        raise RuntimeError(
            "playwright is not installed. On the Mac: "
            "pip install playwright && playwright install chromium") from e

    bodies: list[dict] = []

    def on_response(resp):                                  # pragma: no cover
        url = resp.url
        if not any(h in url for h in INTERCEPT_HINTS):
            return
        ctype = (resp.headers or {}).get("content-type", "")
        if "json" not in ctype:
            return
        try:
            text = resp.text()
            append_raw("pinnacle", url, resp.status, text)
            bodies.append({"url": url, "json": json.loads(text)})
        except Exception as e:
            log.debug("pinnacle intercept skip %s: %s", url, e)

    with sync_playwright() as pw:                           # pragma: no cover
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("response", on_response)
        page.goto(MATCHUPS_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3_000)
        browser.close()

    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        (debug_dir / f"pinnacle-intercepts-{stamp}.json").write_text(
            json.dumps(bodies, indent=1, default=str), encoding="utf-8")
        log.info("pinnacle: dumped %d intercepted bodies to %s",
                 len(bodies), debug_dir)
    return bodies


def parse_intercepts(bodies: list[dict], captured_at: datetime,
                     capture_kind: str) -> list[OddsCapture]:
    """Join matchup fixtures with their straight-moneyline prices.

    Expected shapes (guest API; unvalidated until first live run):
    - a matchups list: [{"id", "startTime", "participants":
        [{"alignment": "home"/"away", "name": ...}, ...], ...}]
    - a markets list: [{"matchupId", "type": "moneyline", "period": 0,
        "prices": [{"designation": "home"/"away", "price": <american>}]}]
    Anything that doesn't fit is skipped and counted; zero parses with
    nonzero intercepts logs loudly so the first run points at --debug.
    """
    fixtures: dict[str, dict] = {}
    prices: dict[str, dict[str, float]] = {}
    for b in bodies:
        payload = b.get("json")
        items = payload if isinstance(payload, list) else [payload]
        for it in items:
            if not isinstance(it, dict):
                continue
            parts = it.get("participants")
            if it.get("id") is not None and isinstance(parts, list):
                names = {p.get("alignment"): p.get("name")
                         for p in parts if isinstance(p, dict)}
                if names.get("home") and names.get("away"):
                    fixtures[str(it["id"])] = {
                        "home": names["home"], "away": names["away"],
                        "start": it.get("startTime")}
            if (it.get("type") == "moneyline"
                    and it.get("matchupId") is not None
                    and it.get("period") in (0, None)):
                got: dict[str, float] = {}
                for pr in it.get("prices", []):
                    d = pr.get("designation")
                    if d in ("home", "away") and pr.get("price") is not None:
                        try:
                            got[d] = _price_to_decimal(pr["price"])
                        except ValueError:
                            pass
                if set(got) == {"home", "away"}:
                    prices[str(it["matchupId"])] = got

    out: list[OddsCapture] = []
    for mid, fx in fixtures.items():
        pr = prices.get(mid)
        if not pr:
            continue
        out.append(OddsCapture(
            captured_at=captured_at, source="pinnacle",
            capture_kind=capture_kind, book_event_id=mid,
            book_home=fx["home"], book_away=fx["away"],
            book_start_ts=fx.get("start"), book_market_key="moneyline",
            price_home=pr["home"], price_away=pr["away"]))
    if bodies and not out:
        log.warning(
            "pinnacle: %d intercepted bodies, 0 parsed fixtures — the guest "
            "API shape differs from the assumed one. Re-run with --debug and "
            "inspect the dump (first-live-run protocol, LOG entry 25).",
            len(bodies))
    return out


def fetch_valorant_fixtures(captured_at: datetime, capture_kind: str,
                            debug_dir: Path | None = None
                            ) -> list[OddsCapture]:      # pragma: no cover
    return parse_intercepts(harvest_page_json(debug_dir), captured_at,
                            capture_kind)
