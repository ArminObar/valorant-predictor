"""API contract tests against a temp data dir (no global state)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from vpredict.serving.api import create_app
from vpredict.serving.ledger import Ledger


def _client(tmp_path):
    return TestClient(create_app(data_dir=tmp_path))


def test_health_and_empty_states(tmp_path):
    c = _client(tmp_path)
    h = c.get("/api/health").json()
    assert h["ok"] is True and h["model_version"] is None
    up = c.get("/api/upcoming").json()
    assert up["predictions"] == []
    sb = c.get("/api/scoreboard").json()
    assert sb["summary"]["n_graded"] == 0 and sb["graded"] == []
    assert "error" in c.get("/api/model").json()


def test_upcoming_and_scoreboard_roundtrip(tmp_path):
    now = datetime.now(timezone.utc)
    pj = tmp_path / "processed" / "upcoming_predictions.json"
    pj.parent.mkdir(parents=True)
    pj.write_text(json.dumps({
        "generated_at": now.isoformat(), "model_version": "vtest",
        "predictions": [{"match_id": "u1", "team1_name": "A",
                         "team2_name": "B", "p_model": 0.61, "p_elo": 0.55}]}))
    led = Ledger(tmp_path / "serving" / "ledger.sqlite")
    led.insert_prediction(match_id="g1", start_ts=now + timedelta(hours=1),
                          team1="a", team2="b", team1_name="A", team2_name="B",
                          event="E", best_of=3, p_model=0.7, p_elo=0.5,
                          model_version="vtest", now=now)
    led.close()

    c = _client(tmp_path)
    up = c.get("/api/upcoming").json()
    assert up["predictions"][0]["match_id"] == "u1"
    sb = c.get("/api/scoreboard").json()
    assert sb["summary"]["n_pending"] == 1
    assert sb["pending"][0]["match_id"] == "g1"
