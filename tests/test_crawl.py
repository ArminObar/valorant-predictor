"""Top-up vs backfill semantics, against a canned offline fetcher.

Field-found bug: the original crawler treated an all-known listing page as
"caught up" unconditionally, so raising max_pages after an initial crawl
returned 0 instantly and history could never be deepened. These tests pin the
two paths: crawl_results (top-up) keeps that early exit; backfill_results walks
straight through known pages, using STORED start times for the `since` stop
rule, and never refetches a known match page.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vpredict import config
from vpredict.scraping import crawl


def _card(mid: str, slug: str) -> str:
    return f"""
    <a class="wf-module-item match-item" href="/{mid}/{slug}">
      <div class="ml-status">Completed</div>
      <div class="match-item-vs-team-name"><div class="text-of">A</div></div>
      <div class="match-item-vs-team-name"><div class="text-of">B</div></div>
      <div class="match-item-event">Cup</div>
    </a>"""


def _listing(*cards: str) -> str:
    return f"<html><body><div class='wf-label'>date</div>{''.join(cards)}</body></html>"


def _match_page(utc_ts: str) -> str:
    return f"""<html><body>
    <div class="match-header-date">
      <div class="moment-tz-convert" data-utc-ts="{utc_ts}"></div>
    </div>
    <a class="match-header-link mod-1" href="/team/1/a">
      <div class="match-header-link-name mod-1"><div class="wf-title-med">A</div></div></a>
    <a class="match-header-link mod-2" href="/team/2/b">
      <div class="match-header-link-name mod-2"><div class="wf-title-med">B</div></div></a>
    <div class="match-header-vs-score">
      <span class="match-header-vs-score-winner">2</span><span>:</span><span>0</span></div>
    <div class="match-header-vs-note">Final</div>
    <div class="match-header-vs-note">Bo3</div>
    </body></html>"""


class FakeFetcher:
    """Duck-typed PoliteFetcher: canned pages, zero network, counts requests."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.stats = {"network": 0, "cache_hits": 0}
        self.requested: list[str] = []

    def get(self, url: str, *, max_cache_age_s: float | None = None) -> str:
        self.stats["network"] += 1
        self.requested.append(url)
        return self.pages[url]


BASE = config.VLR_BASE
SINCE = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def pages() -> dict[str, str]:
    # Listings newest-first: page1 = matches 300, 200; page2 = match 100; page3 empty.
    return {
        f"{BASE}/matches/results?page=1": _listing(_card("300", "x"), _card("200", "y")),
        f"{BASE}/matches/results?page=2": _listing(_card("100", "z")),
        f"{BASE}/matches/results?page=3": "<html><body></body></html>",
        f"{BASE}/300/x": _match_page("2026-07-10 12:00:00"),
        f"{BASE}/200/y": _match_page("2026-07-05 12:00:00"),
        f"{BASE}/100/z": _match_page("2026-06-20 12:00:00"),
    }


def test_topup_stops_at_first_all_known_page(tmp_path, pages):
    sp = tmp_path / "m.jsonl"
    # First run from empty: everything within the window is stored.
    assert crawl.crawl_results(SINCE, max_pages=10, fetcher=FakeFetcher(pages),
                               store_path=sp) == 3
    # Second run: page 1 is all-known -> stop immediately, one listing fetch,
    # zero match-page fetches. This is the cheap cron path.
    f = FakeFetcher(pages)
    assert crawl.crawl_results(SINCE, max_pages=10, fetcher=f, store_path=sp) == 0
    assert f.stats["network"] == 1
    assert all("/matches/results" in u for u in f.requested)


def test_backfill_walks_through_known_pages(tmp_path, pages):
    """The bug scenario: shallow initial crawl, then a deeper request."""
    sp = tmp_path / "m.jsonl"
    assert crawl.crawl_results(SINCE, max_pages=1, fetcher=FakeFetcher(pages),
                               store_path=sp) == 2   # only page 1
    # Top-up with a bigger max_pages CANNOT deepen (documented behavior)...
    assert crawl.crawl_results(SINCE, max_pages=10, fetcher=FakeFetcher(pages),
                               store_path=sp) == 0
    # ...backfill can, and fetches ONLY the one unknown match page.
    f = FakeFetcher(pages)
    assert crawl.backfill_results(SINCE, max_pages=10, fetcher=f, store_path=sp) == 1
    match_fetches = [u for u in f.requested if "/matches/results" not in u]
    assert match_fetches == [f"{BASE}/100/z"]


def test_backfill_stop_rule_uses_stored_timestamps(tmp_path, pages):
    """A known match older than `since` ends the walk without any parsing."""
    sp = tmp_path / "m.jsonl"
    crawl.crawl_results(SINCE, max_pages=10, fetcher=FakeFetcher(pages), store_path=sp)
    late_since = datetime(2026, 7, 1, tzinfo=timezone.utc)   # match 100 is older
    f = FakeFetcher(pages)
    crawl.backfill_results(late_since, max_pages=10, fetcher=f, store_path=sp)
    # Walk reaches page 2, sees known match 100 dated 2026-06-20 < since, stops:
    # no page-3 listing fetch, no match-page fetches at all.
    assert f"{BASE}/matches/results?page=3" not in f.requested
    assert all("/matches/results" in u for u in f.requested)


class InterruptingFetcher(FakeFetcher):
    """Raises KeyboardInterrupt when a specific URL is requested — simulates
    Ctrl-C partway through a long staged backfill."""

    def __init__(self, pages: dict[str, str], interrupt_on: str):
        super().__init__(pages)
        self.interrupt_on = interrupt_on

    def get(self, url: str, *, max_cache_age_s: float | None = None) -> str:
        if url == self.interrupt_on:
            raise KeyboardInterrupt
        return super().get(url, max_cache_age_s=max_cache_age_s)


def test_interrupt_persists_progress_and_resume_completes(tmp_path, pages):
    """Ctrl-C must not discard hours of parsed work: everything parsed before
    the interrupt is flushed to the store, and a plain re-run finishes the job
    storing only what was missing."""
    from vpredict.data import store as st

    sp = tmp_path / "m.jsonl"
    f = InterruptingFetcher(pages, interrupt_on=f"{BASE}/100/z")   # dies on page 2
    with pytest.raises(KeyboardInterrupt):
        crawl.backfill_results(SINCE, max_pages=10, fetcher=f, store_path=sp)
    assert {m.match_id for m in st.load_matches(sp)} == {"300", "200"}
    # Resume with the same command: only the missing match is fetched/stored.
    f2 = FakeFetcher(pages)
    assert crawl.backfill_results(SINCE, max_pages=10, fetcher=f2, store_path=sp) == 1
    assert {m.match_id for m in st.load_matches(sp)} == {"300", "200", "100"}
    match_fetches = [u for u in f2.requested if "/matches/results" not in u]
    assert match_fetches == [f"{BASE}/100/z"]
