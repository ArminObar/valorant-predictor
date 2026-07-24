"""The refresh cycle's call contract with the crawler.

Field-found bug (production, first deploy): serving/refresh.py called
``crawl_results()`` with no arguments after the top-up/backfill split made
``since`` a required positional — every scheduled cycle logged
"crawl_results() missing 1 required positional argument: 'since'" and the
store never topped up. Nothing had ever imported and dry-run the cycle, so the
TypeError first fired on Render.

These tests pin two things:
1. ``topup_since`` semantics: anchored to the newest COMPLETED stored match
   minus the overlap margin; bootstrap window on an empty store.
2. The cycle end-to-end (heavy steps stubbed) passes the crawler arguments
   that BIND against the real ``crawl_results`` signature — so the next
   signature drift fails here, not in production.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from vpredict import config
from vpredict.data import store
from vpredict.data.schema import Match
from vpredict.scraping import crawl
from vpredict.serving import refresh as refresh_mod

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _m(mid: str, start: datetime, status: str = "completed") -> Match:
    return Match(match_id=mid, start_ts=start, status=status)


# --------------------------------------------------------------- topup_since

def test_topup_since_anchors_to_newest_completed():
    matches = [
        _m("1", NOW - timedelta(days=40)),
        _m("2", NOW - timedelta(days=10)),                # newest completed
        _m("3", NOW + timedelta(days=1), status="upcoming"),  # must be ignored
    ]
    got = refresh_mod.topup_since(matches, NOW)
    assert got == (NOW - timedelta(days=10)
                   - timedelta(days=config.TOPUP_OVERLAP_DAYS))


def test_topup_since_empty_store_uses_bootstrap_window():
    got = refresh_mod.topup_since([], NOW)
    assert got == NOW - timedelta(days=config.TOPUP_BOOTSTRAP_DAYS)
    assert got.tzinfo is not None


# ------------------------------------------------- cycle -> crawler contract

def test_refresh_cycle_calls_crawl_results_with_bindable_args(tmp_path, monkeypatch):
    """Run the real refresh_cycle with heavy steps stubbed and assert the
    crawler call binds against the REAL crawl_results signature.

    On the pre-fix code this fails exactly the way production did: the stub is
    invoked with no arguments and signature binding raises
    ``missing a required argument: 'since'``.
    """
    # Real (tiny) store on disk so the since computation exercises load_matches.
    newest = NOW - timedelta(days=2)
    matches_path = tmp_path / "matches.jsonl"
    store.upsert_matches(
        [_m("1", NOW - timedelta(days=9)), _m("2", newest)], path=matches_path)
    monkeypatch.setattr(config, "MATCHES_JSONL", matches_path)
    monkeypatch.setattr(config, "UPCOMING_JSONL", tmp_path / "upcoming.jsonl")
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)  # no bundle on disk

    calls: list[tuple[tuple, dict]] = []

    def fake_crawl_results(*args, **kwargs):
        calls.append((args, kwargs))
        return 7

    # Capture the REAL signature before patching — the recorded call is bound
    # against it below, which is what catches the next signature drift.
    real_sig = inspect.signature(crawl.crawl_results)

    # refresh_cycle imports these lazily from their home modules, so patching
    # the home-module attributes intercepts the calls.
    monkeypatch.setattr(crawl, "crawl_results", fake_crawl_results)
    monkeypatch.setattr(crawl, "crawl_upcoming", lambda *a, **k: [])
    import vpredict.modeling.train as train_mod
    monkeypatch.setattr(train_mod, "train_and_save",
                        lambda *a, **k: {"stub": True}, raising=False)
    monkeypatch.setattr(train_mod, "load_bundle",
                        lambda *a, **k: {"stub": True}, raising=False)

    class StubLedger:
        def grade(self, matches, now=None):
            return 0

        def close(self):
            return None

    monkeypatch.setattr(refresh_mod, "Ledger", StubLedger)

    out = refresh_mod.refresh_cycle(crawl=True)

    assert len(calls) == 1, f"crawl_results not called exactly once: {out}"
    args, kwargs = calls[0]

    # The contract: whatever the cycle passes must bind against the real
    # signature. On the pre-fix code this raises the production error verbatim.
    ba = real_sig.bind(*args, **kwargs)

    since = ba.arguments["since"]
    assert isinstance(since, datetime) and since.tzinfo is not None
    assert since == newest - timedelta(days=config.TOPUP_OVERLAP_DAYS)
    assert out["crawl"] == {"since": since.isoformat(), "stored": 7}
