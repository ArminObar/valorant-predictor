"""FastAPI app serving the public scoreboard.

Endpoints:
  GET /api/health      liveness + model version if a bundle exists
  GET /api/upcoming    latest pre-match predictions (as published to the ledger)
  GET /api/scoreboard  graded ledger rows + rolling model-vs-Elo metrics
  GET /api/model       bundle metadata (never the fitted objects)
  /                    the built frontend (frontend/dist), if present

Background refresh: Render/Railway persistent disks attach to a single
service, so a separate cron worker cannot see the web service's ledger.
Setting VPREDICT_REFRESH=1 therefore runs the refresh cycle (top-up crawl ->
grade -> maybe retrain -> predict upcoming) in a daemon thread inside this
process, every VPREDICT_REFRESH_INTERVAL_S seconds (default 21600 = 6h).
scripts/refresh.py remains for manual runs or real cron on a box with its own
disk.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from vpredict.frontend_locate import locate_frontend_dist

from .. import config
from .ledger import Ledger

log = logging.getLogger("vpredict.api")


def _bundle_meta(bundle_path: Path) -> dict | None:
    if not bundle_path.exists():
        return None
    try:
        from ..modeling.train import load_bundle
        b = load_bundle(bundle_path)
        return {k: v for k, v in b.items()
                if k not in ("model", "calibrator")}
    except Exception as e:                                   # pragma: no cover
        log.warning("bundle unreadable: %s", e)
        return None


def create_app(data_dir: Path | str | None = None) -> FastAPI:
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    ledger_path = data_dir / "serving" / "ledger.sqlite"
    predictions_json = data_dir / "processed" / "upcoming_predictions.json"
    bundle_path = data_dir / "models" / "model.joblib"
    dist = locate_frontend_dist()

    app = FastAPI(title="vpredict", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health() -> dict:
        meta = _bundle_meta(bundle_path)
        return {"ok": True,
                "ts": datetime.now(timezone.utc).isoformat(),
                "model_version": meta["version"] if meta else None,
                "synthetic_model": bool(meta and meta.get("synthetic_data"))}

    @app.get("/api/upcoming")
    def upcoming() -> JSONResponse:
        if predictions_json.exists():
            return JSONResponse(json.loads(predictions_json.read_text()))
        return JSONResponse({"generated_at": None, "model_version": None,
                             "predictions": []})

    @app.get("/api/calibration")
    def calibration() -> dict:
        from ..evaluation.calibration import monitor_report
        from ..evaluation.tiers import classify_tier
        led = Ledger(ledger_path)
        try:
            return monitor_report(led.rows(graded=True, limit=100000),
                                  tier_of=classify_tier)
        finally:
            led.close()

    @app.get("/api/scoreboard")
    def scoreboard() -> dict:
        led = Ledger(ledger_path)
        try:
            return {"summary": led.summary(),
                    "graded": led.rows(graded=True, limit=300),
                    "pending": led.rows(graded=False, limit=100)}
        finally:
            led.close()

    @app.get("/api/markets")
    def markets() -> JSONResponse:
        path = data_dir / "processed" / "markets.json"
        if path.exists():
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
        return JSONResponse({
            "generated_at": None, "section": "LIVE",
            "gate": {"n_graded": 0,
                     "required": config.EV_MIN_GRADED_PICKS,
                     "ev_validated": False},
            "summary": None, "by_tier": {}, "by_market": {}, "picks": []})

    @app.post("/api/ingest/markets")
    async def ingest_markets(request: Request) -> JSONResponse:
        """Receives the derived markets report from the Mac-side publisher
        (scripts/publish_markets.py). Derived view only — overwriting it can
        never touch the ledger or the odds log. Guarded by a shared bearer
        token; disabled entirely when the env var is unset."""
        token = os.environ.get("VPREDICT_INGEST_TOKEN")
        if not token:
            return JSONResponse({"error": "ingest disabled: "
                                 "VPREDICT_INGEST_TOKEN not set"},
                                status_code=503)
        got = request.headers.get("authorization", "")
        if not hmac.compare_digest(got, f"Bearer {token}"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.body()
        if len(body) > 5_000_000:
            return JSONResponse({"error": "report too large"},
                                status_code=413)
        try:
            report = json.loads(body)
        except ValueError:
            return JSONResponse({"error": "not JSON"}, status_code=400)
        if not isinstance(report, dict) or "picks" not in report:
            return JSONResponse({"error": "not a markets report"},
                                status_code=400)
        path = data_dir / "processed" / "markets.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
        tmp.replace(path)
        return JSONResponse({"ok": True,
                             "picks": len(report.get("picks", []))})

    @app.get("/api/model")
    def model() -> dict:
        meta = _bundle_meta(bundle_path)
        return meta or {"error": "no trained bundle yet — run scripts/train.py"}

    if dist is not None:
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    if os.environ.get("VPREDICT_REFRESH", "0") == "1":
        interval = int(os.environ.get("VPREDICT_REFRESH_INTERVAL_S", "21600"))

        def _loop() -> None:                                  # pragma: no cover
            # Subprocess, not in-process: the cycle's memory returns to the
            # OS when the child exits, and an OOM kill (exit 137 / SIGKILL)
            # takes down the child while the API keeps serving — the
            # in-process version died with it (LOG entry 22).
            cmd = [sys.executable, "-m", "vpredict.serving.refresh"]
            while True:
                t0 = time.monotonic()
                try:
                    rc = subprocess.run(cmd).returncode
                    dur = time.monotonic() - t0
                    if rc == 0:
                        log.info("refresh subprocess ok in %.0fs", dur)
                    elif rc in (137, -9):
                        log.error("refresh subprocess OOM-killed after %.0fs "
                                  "(exit %s); API unaffected, next attempt "
                                  "in %ss", dur, rc, interval)
                    else:
                        log.error("refresh subprocess exited %s after %.0fs",
                                  rc, dur)
                except Exception as e:
                    log.error("refresh subprocess failed to run: %s", e)
                time.sleep(interval)

        threading.Thread(target=_loop, daemon=True,
                         name="vpredict-refresh").start()
        log.info("refresh scheduler enabled (subprocess), every %ss", interval)

    return app


app = create_app()
