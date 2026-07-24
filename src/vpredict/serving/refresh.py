"""One refresh cycle: top-up crawl -> grade the ledger -> retrain if stale ->
predict upcoming. Used by scripts/refresh.py (cron/manual) and by the API's
in-process scheduler (VPREDICT_REFRESH=1). Each step is fault-isolated so a
transient failure in one doesn't stop the others; a robots.txt disallow stops
crawling entirely (conduct rules) but never blocks grading or serving."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from .. import config
from ..data import store
from ..memprof import phase
from .ledger import Ledger

log = logging.getLogger("vpredict.refresh")


def _needs_retrain(now: datetime) -> tuple[bool, str]:
    # Measurement override (memharness --force-retrain): make the cycle
    # exercise its heaviest path on demand. Never set in production.
    if os.environ.get("VPREDICT_FORCE_RETRAIN") == "1":
        return True, "forced (VPREDICT_FORCE_RETRAIN=1)"
    bundle_path = config.MODELS_DIR / "model.joblib"
    if not bundle_path.exists():
        return True, "no bundle"
    try:
        from ..modeling.train import load_bundle
        b = load_bundle(bundle_path)
        trained_at = datetime.fromisoformat(b["trained_at"])
        if now - trained_at >= timedelta(days=config.RETRAIN_MAX_AGE_DAYS):
            return True, f"bundle older than {config.RETRAIN_MAX_AGE_DAYS}d"
        n_now = len(store.load_matches(config.MATCHES_JSONL))
        if n_now - int(b.get("n_matches", 0)) >= config.RETRAIN_NEW_MATCHES:
            return True, f"{n_now - int(b.get('n_matches', 0))} new matches"
        return False, "bundle fresh"
    except Exception as e:
        return True, f"bundle unreadable ({e})"


def topup_since(matches: list, now: datetime) -> datetime:
    """Lower time bound for the scheduled top-up crawl (crawl_results).

    Anchored to the newest COMPLETED match already in the store, minus
    ``config.TOPUP_OVERLAP_DAYS`` — listings are newest-first, but entries can
    appear slightly out of order, and anchoring to the store (rather than to
    "now minus a fixed window") means a top-up self-heals after an outage of
    any length. With an empty store there is nothing to anchor to: bound the
    first crawl to ``config.TOPUP_BOOTSTRAP_DAYS``; deepening history beyond
    that is backfill_results's job, not the scheduler's.
    """
    completed = [m.start_ts for m in matches if m.status == "completed"]
    if completed:
        return max(completed) - timedelta(days=config.TOPUP_OVERLAP_DAYS)
    return now - timedelta(days=config.TOPUP_BOOTSTRAP_DAYS)


def refresh_cycle(crawl: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    out: dict = {"ts": now.isoformat()}

    if crawl:
        with phase("crawl"):
            try:
                from ..scraping.crawl import crawl_results
                # Transient full store load; the list is dropped as soon as
                # topup_since returns, well before the memory-heavy steps.
                since = topup_since(store.load_matches(config.MATCHES_JSONL),
                                    now)
                out["crawl"] = {"since": since.isoformat(),
                                "stored": crawl_results(since)}
            except Exception as e:
                log.error("results crawl failed: %s", e)
                out["crawl"] = {"error": str(e)}

    with phase("grade"):
        try:
            matches = store.load_matches(config.MATCHES_JSONL)
            led = Ledger()
            out["graded"] = led.grade(matches)
            led.close()
        except Exception as e:
            log.error("grading failed: %s", e)
            matches, out["graded"] = [], {"error": str(e)}

    with phase("train"):
        try:
            retrain, why = _needs_retrain(now)
            out["retrain"] = why
            if retrain:
                from ..modeling.train import train_and_save
                out["train"] = {k: v for k, v in train_and_save().items()
                                if k != "path"}
        except Exception as e:
            log.error("retrain failed: %s", e)
            out["train"] = {"error": str(e)}

    with phase("predict"):
        try:
            from ..modeling.train import load_bundle
            bundle = load_bundle()
            if crawl:
                from ..scraping.crawl import crawl_upcoming
                upcoming = crawl_upcoming()
            else:
                upcoming = store.load_matches(config.UPCOMING_JSONL)
            upcoming = [m for m in upcoming
                        if m.start_ts > now and m.status in ("upcoming", "live")]
            if upcoming:
                led = Ledger()
                out["predict"] = __import__(
                    "vpredict.modeling.predict", fromlist=["run_predictions"]
                ).run_predictions(bundle, matches or store.load_matches(
                    config.MATCHES_JSONL), upcoming, led, now=now)
                led.close()
            else:
                out["predict"] = {"upcoming": 0}
        except Exception as e:
            log.error("prediction failed: %s", e)
            out["predict"] = {"error": str(e)}

    log.info("refresh cycle: %s", out)
    return out
