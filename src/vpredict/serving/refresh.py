"""One refresh cycle: top-up crawl -> grade the ledger -> retrain if stale ->
predict upcoming. Used by scripts/refresh.py (cron/manual) and by the API's
in-process scheduler (VPREDICT_REFRESH=1). Each step is fault-isolated so a
transient failure in one doesn't stop the others; a robots.txt disallow stops
crawling entirely (conduct rules) but never blocks grading or serving."""
from __future__ import annotations

import json
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
        # A deploy that changes the model definition (features, calibration,
        # prediction behavior) bumps BUNDLE_BEHAVIOR_REV; a bundle trained
        # under an older rev retrains exactly once so serving converges to
        # the deployed definition without waiting out the age cadence
        # (LOG entry 36; pre-rev bundles carry no key and fire the same
        # way, like LOG entry 26's n_store_records convergence).
        rev = b.get("behavior_rev")
        if rev != config.BUNDLE_BEHAVIOR_REV:
            return True, (f"model definition changed (behavior rev "
                          f"{rev} -> {config.BUNDLE_BEHAVIOR_REV}): "
                          "retrain once")
        trained_at = datetime.fromisoformat(b["trained_at"])
        if now - trained_at >= timedelta(days=config.RETRAIN_MAX_AGE_DAYS):
            return True, f"bundle older than {config.RETRAIN_MAX_AGE_DAYS}d"
        # Compare like with like: count_matches counts TOTAL store records,
        # so the baseline must too. Bundles from before this fix carry only
        # n_matches (USABLE matches, ~1.3k lower), which made "new matches"
        # permanently >= 100 and retrained every cycle (LOG entry 26).
        n_now = store.count_matches(config.MATCHES_JSONL)
        base = b.get("n_store_records")
        if base is None:
            return True, "pre-fix bundle (no n_store_records): retrain once"
        if n_now - int(base) >= config.RETRAIN_NEW_MATCHES:
            return True, f"{n_now - int(base)} new matches"
        return False, "bundle fresh"
    except Exception as e:
        return True, f"bundle unreadable ({e})"


def topup_since(matches, now: datetime) -> datetime:
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


def _odds_phase(out: dict) -> None:
    """Cloudbet capture, server-side. Skips loudly-but-safely without a key
    (the Pinnacle leg still arrives via /api/ingest/odds from the Mac)."""
    if not os.environ.get("CLOUDBET_API_KEY"):
        out["odds"] = {"skipped": "no CLOUDBET_API_KEY"}
        return
    from ..odds.capture import acquire_capture_lock, run_once
    lock = acquire_capture_lock()
    if lock is None:
        out["odds"] = {"skipped": "capture already running"}
        return
    try:
        report, _ = run_once(["cloudbet"], prefer_local=True)
        out["odds"] = report
    finally:
        lock.close()


def _trends_phase(out: dict) -> None:
    """Build trends.json from the store: a pure derived view, rebuilt each
    full cycle. Kept out of the 10-minute odds tick on purpose — nothing
    in it changes faster than the results crawl (ASSUMPTIONS §61)."""
    from ..data.trends import build_trends
    if not config.MATCHES_JSONL.exists():
        out["trends"] = {"skipped": "no store yet"}
        return
    report = build_trends(store.iter_matches(config.MATCHES_JSONL))
    path = config.TRENDS_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    tmp.replace(path)
    out["trends"] = {"teams": report["n_teams"]}


def _markets_phase(out: dict) -> None:
    """Build markets.json in-cycle from the ledger (read directly, no
    pending cap — LOG entry 45) and the server odds log. Atomic write, same
    derived-view semantics as the old Mac push."""
    from ..odds.markets import build_markets_report
    from ..odds.schema import iter_captures
    if not config.ODDS_JSONL.exists():
        out["markets"] = {"skipped": "no odds log yet"}
        return
    led = Ledger()
    try:
        rows = led.rows(graded=None, limit=100000)
    finally:
        led.close()
    report = build_markets_report(rows, list(iter_captures()))
    path = config.PROCESSED_DIR / "markets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    tmp.replace(path)
    out["markets"] = {"picks": len(report.get("picks", [])),
                      "gate": report.get("gate"),
                      "skipped": report.get("skipped")}


def refresh_cycle(crawl: bool = True,
                  odds_only: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    out: dict = {"ts": now.isoformat()}

    if odds_only:
        with phase("odds"):
            try:
                _odds_phase(out)
            except Exception as e:
                log.error("odds capture failed: %s", e)
                out["odds"] = {"error": str(e)}
        with phase("markets"):
            try:
                _markets_phase(out)
            except Exception as e:
                log.error("markets build failed: %s", e)
                out["markets"] = {"error": str(e)}
        log.info("odds tick: %s", out)
        return out

    # Run-once, marker-guarded (LOG entry 29). Must precede the crawl so a
    # store written by the old parser is corrected before rows from the fixed
    # parser can mix in; a marker file makes every later call a no-op.
    with phase("tz_migration"):
        try:
            from ..data.migrate import migrate_tz_if_needed, tz_migration_applied
            already = tz_migration_applied()
            rep = migrate_tz_if_needed()
            if not already:
                out["tz_migration"] = rep
        except Exception as e:
            log.error("tz migration failed: %s", e)
            out["tz_migration"] = {"error": str(e)}

    if crawl:
        with phase("crawl"):
            try:
                from ..scraping.crawl import crawl_results
                since = topup_since(
                    store.iter_matches(config.MATCHES_JSONL), now)
                out["crawl"] = {"since": since.isoformat(),
                                "stored": crawl_results(since)}
            except Exception as e:
                log.error("results crawl failed: %s", e)
                out["crawl"] = {"error": str(e)}

        # Runs before grade so a healed result grades in the SAME cycle.
        with phase("heal"):
            try:
                from ..scraping.crawl import heal_stale_nonfinal
                rep = heal_stale_nonfinal()
                if rep["checked"]:
                    out["heal"] = rep
            except Exception as e:
                log.error("heal pass failed: %s", e)
                out["heal"] = {"error": str(e)}

    with phase("grade"):
        try:
            led = Ledger()
            out["graded"] = led.grade(store.iter_matches(config.MATCHES_JSONL))
            # Totals grading metadata for rows graded before the column
            # existed; a no-op stream scan once every row has it.
            filled = led.backfill_maps_played(
                store.iter_matches(config.MATCHES_JSONL))
            if filled:
                out["maps_played_backfilled"] = filled
            renamed = led.backfill_names(
                store.iter_matches(config.MATCHES_JSONL))
            if renamed:
                out["names_backfilled"] = renamed
            led.close()
        except Exception as e:
            log.error("grading failed: %s", e)
            out["graded"] = {"error": str(e)}

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
                ).run_predictions(
                    bundle, store.iter_matches(config.MATCHES_JSONL),
                    upcoming, led, now=now)
                led.close()
            else:
                out["predict"] = {"upcoming": 0}
        except Exception as e:
            log.error("prediction failed: %s", e)
            out["predict"] = {"error": str(e)}

    with phase("odds"):
        try:
            _odds_phase(out)
        except Exception as e:
            log.error("odds capture failed: %s", e)
            out["odds"] = {"error": str(e)}
    with phase("markets"):
        try:
            _markets_phase(out)
        except Exception as e:
            log.error("markets build failed: %s", e)
            out["markets"] = {"error": str(e)}
    with phase("trends"):
        try:
            _trends_phase(out)
        except Exception as e:
            log.error("trends build failed: %s", e)
            out["trends"] = {"error": str(e)}

    log.info("refresh cycle: %s", out)
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI for one refresh cycle: `python -m vpredict.serving.refresh`.

    The in-process scheduler (api.py, VPREDICT_REFRESH=1) spawns exactly this
    module as a subprocess so the cycle's memory returns to the OS on exit
    and an OOM kill takes down the child, never the API (LOG entry 22).
    scripts/refresh.py delegates here so cron and the scheduler share one
    entrypoint.
    """
    import argparse
    import json as _json

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(
        description="One full refresh cycle "
                    "(crawl -> grade -> retrain if stale -> predict).")
    ap.add_argument("--no-crawl", action="store_true",
                    help="skip network steps (grade + retrain + predict "
                         "from disk)")
    ap.add_argument("--odds-only", action="store_true",
                    help="light pass: cloudbet capture + markets build only")
    args = ap.parse_args(argv)
    print(_json.dumps(refresh_cycle(crawl=not args.no_crawl,
                                    odds_only=args.odds_only),
                      indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
