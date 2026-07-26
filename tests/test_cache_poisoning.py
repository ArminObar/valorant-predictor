"""Cache poisoning regression (LOG entry 41).

The proven production failure: a match page cached while the match sat on
the upcoming radar (pre-completion body) is served forever to the
completed crawl, which then stores a 'live' record that can never grade.
Pinned here: the completed path detects the stale body and refetches; a
fresh body that still is not final is never stored by that path; the
healing pass releases already-trapped rows and leaves genuinely
in-progress or long-dead fixtures alone.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_crawl import _card, _listing, _match_page  # noqa: E402

from vpredict import config                            # noqa: E402
from vpredict.data import store                        # noqa: E402
from vpredict.data.schema import Match                 # noqa: E402
from vpredict.scraping import crawl                    # noqa: E402

BASE = config.VLR_BASE
SINCE = datetime(2026, 6, 1, tzinfo=timezone.utc)
NOW = datetime(2026, 7, 25, 20, 0, tzinfo=timezone.utc)


def _match_page_live(utc_ts: str) -> str:
    """Same layout as the completed fixture, but the status note says LIVE
    and no winner is marked — exactly what the upcoming radar caches."""
    return f"""<html><body>
    <div class="match-header-date">
      <div class="moment-tz-convert" data-utc-ts="{utc_ts}"></div>
    </div>
    <a class="match-header-link mod-1" href="/team/1/a">
      <div class="match-header-link-name mod-1"><div class="wf-title-med">A</div></div></a>
    <a class="match-header-link mod-2" href="/team/2/b">
      <div class="match-header-link-name mod-2"><div class="wf-title-med">B</div></div></a>
    <div class="match-header-vs-score">
      <span>0</span><span>:</span><span>0</span></div>
    <div class="match-header-vs-note">LIVE</div>
    <div class="match-header-vs-note">Bo3</div>
    </body></html>"""


class PoisonedFetcher:
    """Duck-typed PoliteFetcher modeling the two-layer reality: default
    reads serve the (possibly stale) cache view; max_cache_age_s=0 reaches
    the network view. Counts forced fetches."""

    def __init__(self, cache_view: dict[str, str], network_view: dict[str, str]):
        self.cache_view = cache_view
        self.network_view = network_view
        self.stats = {"network": 0, "cache_hits": 0}
        self.requested: list[str] = []
        self.forced: list[str] = []

    def get(self, url: str, *, max_cache_age_s: float | None = None) -> str:
        self.requested.append(url)
        if max_cache_age_s == 0:
            self.forced.append(url)
            self.stats["network"] += 1
            return self.network_view[url]
        if url in self.cache_view:
            self.stats["cache_hits"] += 1
            return self.cache_view[url]
        self.stats["network"] += 1
        return self.network_view[url]


def _views(match_body_fresh: str) -> tuple[dict, dict]:
    listing = {
        f"{BASE}/matches/results?page=1": _listing(_card("900", "x")),
        f"{BASE}/matches/results?page=2": _listing(),
    }
    cache = dict(listing)
    cache[f"{BASE}/900/x"] = _match_page_live("2026-07-25 04:00:00")
    network = dict(listing)
    network[f"{BASE}/900/x"] = match_body_fresh
    return cache, network


def test_poisoned_cache_is_refetched_and_completed_stored(tmp_path):
    cache, network = _views(_match_page("2026-07-25 04:00:00"))
    f = PoisonedFetcher(cache, network)
    sp = tmp_path / "m.jsonl"
    assert crawl.crawl_results(SINCE, max_pages=5, fetcher=f,
                               store_path=sp) == 1
    assert f.forced == [f"{BASE}/900/x"]          # exactly one forced refetch
    (m,) = store.load_matches(sp)
    assert m.match_id == "900"
    assert m.status == "completed" and m.winner == "team1"


def test_fresh_nonfinal_body_is_never_stored_by_completed_path(tmp_path):
    # Network truth ALSO says live (listing/page race): nothing is stored,
    # the id stays unknown, and the next crawl will retry it.
    cache, network = _views(_match_page_live("2026-07-25 04:00:00"))
    f = PoisonedFetcher(cache, network)
    sp = tmp_path / "m.jsonl"
    assert crawl.crawl_results(SINCE, max_pages=5, fetcher=f,
                               store_path=sp) == 0
    assert f.forced == [f"{BASE}/900/x"]
    assert store.load_matches(sp) == []


def _trapped(mid: str, start: datetime, status: str = "live") -> Match:
    return Match(match_id=mid, start_ts=start, status=status, best_of=3,
                 event="Cup", series="Week", team1_id="1", team1_name="A",
                 team2_id="2", team2_name="B", team1_maps=0, team2_maps=0,
                 maps=[], url=f"{BASE}/{mid}/x")


def test_heal_releases_trapped_row_only(tmp_path):
    sp = tmp_path / "m.jsonl"
    store.upsert_matches([
        _trapped("900", NOW - timedelta(hours=12)),          # trapped
        _trapped("901", NOW - timedelta(hours=1)),           # in progress
        _trapped("902", NOW - timedelta(days=60)),           # beyond lookback
    ], path=sp)
    network = {f"{BASE}/900/x": _match_page("2026-07-25 04:00:00")}
    f = PoisonedFetcher({}, network)
    rep = crawl.heal_stale_nonfinal(fetcher=f, store_path=sp, now=NOW)
    assert rep == {"checked": 1, "healed": 1, "unresolved": 0, "errors": 0}
    assert f.forced == [f"{BASE}/900/x"]          # 901/902 never touched
    by_id = {m.match_id: m for m in store.load_matches(sp)}
    assert by_id["900"].status == "completed" and by_id["900"].winner
    assert by_id["901"].status == "live"          # untouched
    assert by_id["902"].status == "live"          # untouched


def test_heal_leaves_store_alone_when_page_still_nonfinal(tmp_path):
    sp = tmp_path / "m.jsonl"
    store.upsert_matches([_trapped("900", NOW - timedelta(hours=12))],
                         path=sp)
    network = {f"{BASE}/900/x": _match_page_live("2026-07-25 04:00:00")}
    f = PoisonedFetcher({}, network)
    rep = crawl.heal_stale_nonfinal(fetcher=f, store_path=sp, now=NOW)
    assert rep == {"checked": 1, "healed": 0, "unresolved": 1, "errors": 0}
    (m,) = store.load_matches(sp)
    assert m.status == "live"                     # no regression, no guess
