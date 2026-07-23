"""Crawler: listings -> match ids -> match pages -> store.

Design rules (from the build spec):
- robots.txt checked before anything (PoliteFetcher enforces it).
- single thread, >=1s between network requests, everything cached to disk.
- re-runnable: completed match pages are served from cache forever; only
  listing pages and upcoming-match pages have a TTL.
- Tier B (economy/performance tabs) is opt-in; failures there never block.

Two distinct completed-match paths (field-found requirement):
- crawl_results()    incremental TOP-UP. Stops at the first listing page that
                     contains nothing new. Cheap; what a cron job runs.
- backfill_results() historical BACKFILL. Walks straight through pages of
                     already-known matches (their stored start times drive the
                     stop rule, no refetching) until `since` or `max_pages`.
                     What you run to deepen history after raising the window.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config
from ..data import store
from ..data.schema import Match, utcnow
from .http import PoliteFetcher, RobotsDisallowed
from .parse_list import parse_listing
from .parse_match import parse_match_page
from .parse_tabs import parse_econ_tab, parse_performance_tab

log = logging.getLogger("vpredict.crawl")


def _attach_tier_b(fetcher: PoliteFetcher, match: Match) -> None:
    for mp in match.maps:
        try:
            econ_html = fetcher.get(f"{config.VLR_BASE}/{match.match_id}/?game={mp.game_id}&tab=economy")
            econ = parse_econ_tab(econ_html)
            if econ:
                mp.team1_econ, mp.team2_econ = econ
        except RobotsDisallowed:
            raise
        except Exception as e:  # noqa: BLE001 — Tier B must never block
            log.warning("tier B economy failed for %s map %s: %s", match.match_id, mp.map_name, e)
        try:
            perf_html = fetcher.get(f"{config.VLR_BASE}/{match.match_id}/?game={mp.game_id}&tab=performance")
            perf = parse_performance_tab(perf_html)
            if perf:
                for plist in (mp.team1_players, mp.team2_players):
                    for p in plist:
                        row = perf.get(p.name.strip().lower())
                        if row:
                            p.multikills = row["multikills"]
                            p.clutch_wins = row["clutch_wins"]
                            p.plants = row["plants"]
                            p.defuses = row["defuses"]
        except RobotsDisallowed:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("tier B performance failed for %s map %s: %s", match.match_id, mp.map_name, e)


def _crawl_completed(
    since: datetime,
    max_pages: int,
    tier_b: bool,
    fetcher: PoliteFetcher | None,
    store_path: Path,
    stop_when_all_known: bool,
) -> int:
    fetcher = fetcher or PoliteFetcher()
    # match_id -> stored start_ts, so backfill can walk past known matches and
    # still apply the `since` stop rule without refetching anything.
    known_ts: dict[str, datetime] = {
        m.match_id: m.start_ts for m in store.load_matches(store_path)}
    batch: list[Match] = []
    stored_total = 0
    page = 1
    done = False

    def _flush() -> None:
        nonlocal stored_total, batch
        if batch:
            stored_total += store.upsert_matches(batch, path=store_path)
            batch = []

    try:
        while page <= max_pages and not done:
            url = f"{config.VLR_BASE}/matches/results?page={page}"
            html = fetcher.get(url, max_cache_age_s=config.UPCOMING_CACHE_TTL_S)
            cards = [c for c in parse_listing(html) if c.status == "completed"]
            if not cards:
                break
            new_on_page = 0
            for card in cards:
                if card.match_id in known_ts:
                    # Listings are newest-first: once anything on the walk is older
                    # than the window, everything deeper is older too.
                    if known_ts[card.match_id] < since:
                        done = True
                        break
                    continue
                new_on_page += 1
                murl = f"{config.VLR_BASE}{card.href}"
                try:
                    match = parse_match_page(fetcher.get(murl), card.match_id, murl)
                except RobotsDisallowed:
                    raise
                except Exception as e:  # noqa: BLE001 — one bad page must not kill a crawl
                    log.error("failed to parse match %s: %s", card.match_id, e)
                    continue
                match.scraped_at = utcnow()
                if match.start_ts < since:
                    done = True
                    break
                if tier_b and match.status == "completed":
                    _attach_tier_b(fetcher, match)
                batch.append(match)
                known_ts[card.match_id] = match.start_ts
                if len(batch) >= config.CRAWL_FLUSH_MATCHES:
                    _flush()   # long backfills: bound memory and the loss window
            if stop_when_all_known and new_on_page == 0 and not done:
                done = True   # top-up mode: an all-known page means we're caught up
            page += 1
    finally:
        # Interrupts (Ctrl-C) land here: everything parsed so far is persisted.
        # The store write is tmp-then-atomic-replace, so even a kill during the
        # flush itself cannot corrupt matches.jsonl — worst case that one flush
        # simply did not happen and its matches re-parse from cache next run.
        _flush()
    log.info("%s: %d matches stored/updated | pages walked=%d | network=%d cache=%d",
             "top-up" if stop_when_all_known else "backfill",
             stored_total, page - 1, fetcher.stats["network"], fetcher.stats["cache_hits"])
    return stored_total


def crawl_results(
    since: datetime,
    max_pages: int = 300,
    tier_b: bool = False,
    fetcher: PoliteFetcher | None = None,
    store_path: Path = config.MATCHES_JSONL,
) -> int:
    """Incremental top-up of NEW completed matches. Stops at the first listing
    page with nothing unknown on it — fast, suitable for a scheduled job, but
    by design it can never deepen history. Use backfill_results for that."""
    return _crawl_completed(since, max_pages, tier_b, fetcher, store_path,
                            stop_when_all_known=True)


def backfill_results(
    since: datetime,
    max_pages: int = 300,
    tier_b: bool = False,
    fetcher: PoliteFetcher | None = None,
    store_path: Path = config.MATCHES_JSONL,
) -> int:
    """Historical backfill. Walks every listing page — straight through pages
    of already-known matches — until reaching `since` or `max_pages`. Known
    matches are never refetched (their stored start times drive the stop rule),
    and previously fetched match pages come from the disk cache for free."""
    return _crawl_completed(since, max_pages, tier_b, fetcher, store_path,
                            stop_when_all_known=False)


def crawl_upcoming(
    max_pages: int = 3,
    fetcher: PoliteFetcher | None = None,
    store_path: Path = config.UPCOMING_JSONL,
) -> list[Match]:
    """Fetch upcoming matches (short TTL cache) and persist to upcoming.jsonl."""
    fetcher = fetcher or PoliteFetcher()
    out: list[Match] = []
    for page in range(1, max_pages + 1):
        url = f"{config.VLR_BASE}/matches?page={page}" if page > 1 else f"{config.VLR_BASE}/matches"
        html = fetcher.get(url, max_cache_age_s=config.UPCOMING_CACHE_TTL_S)
        for card in parse_listing(html):
            if card.status not in ("upcoming", "live"):
                continue
            murl = f"{config.VLR_BASE}{card.href}"
            try:
                m = parse_match_page(
                    fetcher.get(murl, max_cache_age_s=config.UPCOMING_CACHE_TTL_S),
                    card.match_id, murl)
            except RobotsDisallowed:
                raise
            except Exception as e:  # noqa: BLE001
                log.error("failed to parse upcoming %s: %s", card.match_id, e)
                continue
            m.scraped_at = utcnow()
            out.append(m)
    store.upsert_matches(out, path=store_path)
    return out


def default_since(days: int = 730) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Scrape vlr.gg completed matches (top-up by default).")
    ap.add_argument("--backfill", action="store_true",
                    help="walk past known matches to deepen history")
    ap.add_argument("--since-days", type=int, default=730,
                    help="how far back the window reaches (default 730)")
    ap.add_argument("--max-pages", type=int, default=300)
    ap.add_argument("--tier-b", action="store_true",
                    help="also fetch economy/performance tabs (3x requests)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")
    fn = backfill_results if args.backfill else crawl_results
    n = fn(default_since(args.since_days), max_pages=args.max_pages, tier_b=args.tier_b)
    print(f"stored/updated: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
