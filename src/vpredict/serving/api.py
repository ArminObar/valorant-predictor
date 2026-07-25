"""FastAPI app serving the public scoreboard.

Endpoints:
  GET /api/health      liveness + model version if a bundle exists
  GET /api/upcoming    latest pre-match predictions (as published to the ledger)
  GET /api/scoreboard  graded ledger rows + rolling model-vs-Elo metrics
  GET /api/results     recent-window evaluation summary (publish_results.py)
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
    # Without an explicit handler, the API process's INFO lines (scheduler
    # enabled, subprocess ok/failed) fall to Python's last-resort handler,
    # which emits WARNING and above only — they were silently dropped in
    # production (LOG entry 36). Configure the vpredict tree directly and
    # stop propagation, so exactly one line emits regardless of what the
    # runner (uvicorn, pytest, anything) did to the root logger.
    vlog = logging.getLogger("vpredict")
    if not vlog.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
        vlog.addHandler(h)
    vlog.setLevel(logging.INFO)
    vlog.propagate = False
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

    async def _ingest(request: Request, filename: str,
                      required_key: str) -> JSONResponse:
        """Shared guard for derived-view uploads from the Mac-side scripts.
        Derived views only — overwriting them can never touch the ledger or
        the odds log. Bearer token; disabled entirely when the env var is
        unset."""
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
        if not isinstance(report, dict) or required_key not in report:
            return JSONResponse({"error": f"missing '{required_key}'"},
                                status_code=400)
        path = data_dir / "processed" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
        tmp.replace(path)
        val = report.get(required_key)
        return JSONResponse({"ok": True,
                             "items": len(val) if isinstance(val, (list, dict))
                             else None})

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
        return await _ingest(request, "markets.json", "picks")

    @app.get("/api/backtest")
    def backtest() -> JSONResponse:
        path = data_dir / "processed" / "backtest.json"
        if path.exists():
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
        return JSONResponse({"section": "BACKTEST", "generated_at": None,
                             "per_tier": {}, "window": None,
                             "label": "not yet run"})

    @app.post("/api/ingest/backtest")
    async def ingest_backtest(request: Request) -> JSONResponse:
        return await _ingest(request, "backtest.json", "per_tier")

    @app.get("/api/results")
    def results() -> JSONResponse:
        """Recent-window evaluation summary (both grains + per tier),
        produced only by scripts/evaluate.py and moved here by
        scripts/publish_results.py. Empty shape until first publish."""
        path = data_dir / "processed" / "results_summary.json"
        if path.exists():
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
        return JSONResponse({"generated_at": None, "source": None,
                             "map": None, "series": None, "per_tier": []})

    @app.post("/api/ingest/results")
    async def ingest_results(request: Request) -> JSONResponse:
        return await _ingest(request, "results_summary.json", "series")

    @app.get("/api/match/{match_id}")
    def match_detail(match_id: str) -> JSONResponse:
        """Everything known about one match: the upcoming prediction or the
        frozen ledger row (whichever exists; the ledger wins because it is
        the record), any market picks, and both teams' recent completed
        results for context. Reads the same artifacts the other endpoints
        serve; the team-history part streams the store once."""
        out: dict = {"match_id": match_id, "prediction": None,
                     "ledger": None, "picks": [], "team_history": {}}
        if predictions_json.exists():
            up = json.loads(predictions_json.read_text())
            for p in up.get("predictions", []):
                if str(p.get("match_id")) == match_id:
                    out["prediction"] = p
                    break
        led = Ledger(ledger_path)
        try:
            row = next((r for r in led.rows(graded=None, limit=100000)
                        if str(r["match_id"]) == match_id), None)
            out["ledger"] = row
        finally:
            led.close()
        mk = data_dir / "processed" / "markets.json"
        if mk.exists():
            picks = json.loads(mk.read_text()).get("picks", [])
            out["picks"] = [p for p in picks
                            if str(p.get("match_id")) == match_id]
        src = out["ledger"] or out["prediction"]
        # A pre-0022 unresolved bracket slot: both sides collapsed to one
        # placeholder key. Its frozen call stands (first call per match is
        # immutable, so the resolved fixture could never re-predict this
        # id); it is flagged, excluded from scoring, and must render as a
        # placeholder, never as a normal result.
        _ph = {"", "tbd", "tba"}
        out["placeholder"] = bool(src) and (
            src.get("team1") == src.get("team2")
            or (src.get("team1_name") or "").strip().lower() in _ph
            or (src.get("team2_name") or "").strip().lower() in _ph)
        keys = set()
        if src and not out["placeholder"]:
            keys = {src.get("team1"), src.get("team2")} - {None, ""}
        if keys:
            from ..data import store as _store
            hist: dict[str, list] = {k: [] for k in keys}
            names: dict[str, str] = {}
            for m in _store.iter_matches(config.MATCHES_JSONL):
                if m.status != "completed" or not m.winner:
                    continue
                for side in ("team1", "team2"):
                    k = m.key_team(side)
                    if k in keys:
                        won = (m.winner == side)
                        opp = (m.team2_name if side == "team1"
                               else m.team1_name)
                        names[k] = (m.team1_name if side == "team1"
                                    else m.team2_name)
                        hist[k].append({
                            "start_ts": m.start_ts.isoformat(),
                            "event": m.event, "opponent": opp,
                            "won": bool(won),
                            "score": f"{m.team1_maps}-{m.team2_maps}"
                                     if side == "team1" else
                                     f"{m.team2_maps}-{m.team1_maps}"})
            out["team_history"] = {
                k: {"name": names.get(k, k),
                    "recent": sorted(v, key=lambda r: r["start_ts"])[-5:][::-1]}
                for k, v in hist.items() if v}   # no empty tbd blocks
            # Rating trajectories for the chart: same store, the same Elo
            # family the site's comparison column uses (tuned baseline K
            # from the live bundle when readable), same leakage rule —
            # only matches whose estimated finish precedes this match's
            # start count, so each line ends at the rating the as-of
            # snapshot reports for that cutoff (the frozen p_elo came
            # from the freeze-time store, so late-scraped history can
            # differ slightly). Display context only; the chart
            # never touches the frozen record, and any failure here
            # degrades to "no chart", never to a broken page.
            try:
                import pandas as pd
                from ..modeling.baselines import (elo_trajectory,
                                                  matches_lite_from_maps)
                meta_b = _bundle_meta(bundle_path) or {}
                k_elo = float(meta_b.get("elo_k_baseline")
                              or config.DEFAULT_ELO_K)
                cutoff = pd.Timestamp(src["start_ts"])
                if cutoff.tzinfo is None:
                    cutoff = cutoff.tz_localize("UTC")
                maps_df = _store.maps_frame(
                    _store.iter_matches(config.MATCHES_JSONL))
                traj = {}
                if not maps_df.empty:
                    traj = elo_trajectory(
                        matches_lite_from_maps(maps_df), cutoff, keys,
                        n=config.RATING_TRAJECTORY_N, k=k_elo)
                if traj:
                    out["rating_history"] = {
                        "k": k_elo, "n": config.RATING_TRAJECTORY_N,
                        "cutoff": cutoff.isoformat(),
                        "teams": {t: {"name": names.get(t, t),
                                      "points": pts}
                                  for t, pts in traj.items()}}
            except Exception as e:               # pragma: no cover
                log.warning("rating history unavailable: %s", e)
        return JSONResponse(out)

    @app.get("/api/model")
    def model() -> dict:
        meta = _bundle_meta(bundle_path)
        return meta or {"error": "No trained model yet. Run scripts/train.py."}

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
