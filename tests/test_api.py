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


def test_match_detail_merges_ledger_and_history(tmp_path, monkeypatch):
    """One endpoint, everything known about a match: the frozen row wins as
    the record, and both teams' recent completed results come along."""
    import json
    from datetime import datetime, timedelta, timezone
    from fastapi.testclient import TestClient
    from vpredict import config
    from vpredict.data.schema import Match
    from vpredict.data import store as st
    from vpredict.serving.api import create_app
    from vpredict.serving.ledger import Ledger

    data = tmp_path / "data"
    (data / "processed").mkdir(parents=True)
    (data / "serving").mkdir(parents=True)
    (data / "raw").mkdir(parents=True)
    monkeypatch.setattr(config, "MATCHES_JSONL", data / "raw" / "matches.jsonl")
    t0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    hist = Match(match_id="h1", start_ts=t0, status="completed", best_of=3,
                 team1_id="a", team1_name="Alpha", team2_id="b",
                 team2_name="Beta", winner="team1", team1_maps=2,
                 team2_maps=1)
    st.upsert_matches([hist], config.MATCHES_JSONL)
    led = Ledger(data / "serving" / "ledger.sqlite")
    start = datetime.now(timezone.utc) + timedelta(hours=3)
    led.insert_prediction(match_id="m9", start_ts=start, team1="a",
                          team2="b", team1_name="Alpha", team2_name="Beta",
                          event="Cup", best_of=3, p_model=0.61, p_elo=0.55,
                          model_version="t", low_history=False)
    led.close()
    app = create_app(data_dir=data)
    c = TestClient(app)
    r = c.get("/api/match/m9").json()
    assert r["ledger"]["p_model"] == 0.61 and r["prediction"] is None
    th = r["team_history"]
    assert th["a"]["name"] == "Alpha" and th["a"]["recent"][0]["won"] is True
    assert th["b"]["recent"][0]["score"] == "1-2"
    assert c.get("/api/match/nope").json()["ledger"] is None


def test_match_detail_placeholder_never_renders_as_result(tmp_path, monkeypatch):
    """A pre-0022 collided TBD row: the endpoint flags it, and no empty
    'tbd' history blocks are emitted."""
    from datetime import datetime, timedelta, timezone
    from fastapi.testclient import TestClient
    from vpredict import config
    from vpredict.serving.api import create_app
    from vpredict.serving.ledger import Ledger

    data = tmp_path / "data"
    (data / "serving").mkdir(parents=True)
    (data / "raw").mkdir(parents=True)
    monkeypatch.setattr(config, "MATCHES_JSONL", data / "raw" / "matches.jsonl")
    led = Ledger(data / "serving" / "ledger.sqlite")
    start = datetime.now(timezone.utc) - timedelta(hours=5)
    led.insert_prediction(match_id="ph1", start_ts=start, team1="tbd",
                          team2="tbd", team1_name="TBD", team2_name="TBD",
                          event="Cup", best_of=3, p_model=0.5843, p_elo=0.5,
                          model_version="t", low_history=True,
                          now=start - timedelta(hours=1))
    led.close()
    c = TestClient(create_app(data_dir=data))
    r = c.get("/api/match/ph1").json()
    assert r["placeholder"] is True
    assert r["team_history"] == {}
