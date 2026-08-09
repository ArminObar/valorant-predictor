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


def test_results_endpoint_empty_then_ingest_roundtrip(tmp_path, monkeypatch):
    """Mirror of the markets/backtest ingest contract for /api/results:
    empty-but-shaped before first publish, Bearer-token gated, served
    verbatim after."""
    monkeypatch.setenv("VPREDICT_INGEST_TOKEN", "s3cret")
    c = _client(tmp_path)
    empty = c.get("/api/results").json()
    assert empty["generated_at"] is None and empty["per_tier"] == []

    report = {"generated_at": "2026-07-25T00:00:00+00:00",
              "source": "scripts/evaluate.py", "synthetic": False,
              "store": {"n_matches_usable": 10}, "split": {},
              "selected": {"name": "lr", "calibration": "platt"},
              "map": {"n_rows": 40,
                      "model": {"log_loss": 0.66, "accuracy": 0.60},
                      "elo": {"log_loss": 0.67, "accuracy": 0.59}},
              "series": {"n": 10,
                         "model": {"log_loss": 0.65, "accuracy": 0.62},
                         "elo": {"log_loss": 0.66, "accuracy": 0.61}},
              "per_tier": [{"tier": "tier1", "n_map_rows": 40}]}
    assert c.post("/api/ingest/results", json=report).status_code == 401
    assert c.post("/api/ingest/results", json=report,
                  headers={"Authorization": "Bearer wrong"}
                  ).status_code == 401
    ok = c.post("/api/ingest/results", json=report,
                headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    got = c.get("/api/results").json()
    assert got["series"]["model"]["log_loss"] == 0.65
    assert got["per_tier"][0]["tier"] == "tier1"


def _client_with_dist(tmp_path, monkeypatch):
    """App with a fake built frontend, same trick the security tests use."""
    import vpredict.serving.api as api_mod
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa-shell</html>")
    monkeypatch.setattr(api_mod, "locate_frontend_dist", lambda: dist)
    return TestClient(create_app(data_dir=tmp_path))


def test_spa_fallback_serves_shell_for_client_routes(tmp_path, monkeypatch):
    """Deep links and reloads on client routes get the SPA shell (200),
    with the security headers still applied by the middleware."""
    c = _client_with_dist(tmp_path, monkeypatch)
    for path in ("/upcoming", "/scoreboard", "/model", "/backtest",
                 "/match/562119"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert "spa-shell" in r.text
        assert "Content-Security-Policy" in r.headers
    assert "spa-shell" in c.get("/").text  # the mount's own index intact


def test_spa_fallback_never_masks_api_or_asset_404s(tmp_path, monkeypatch):
    """The fallback is for page URLs only: unknown /api paths stay JSON
    404s, and extensioned paths (missing assets, sensitive-file probes —
    which all carry extensions) stay real 404s."""
    c = _client_with_dist(tmp_path, monkeypatch)
    r = c.get("/api/definitely-not-a-route")
    assert r.status_code == 404 and "spa-shell" not in r.text
    for path in ("/assets/stale-bundle-abc123.js", "/favicon.ico",
                 "/serving/ledger.sqlite"):
        assert c.get(path).status_code == 404, path


def test_trends_endpoint_presets_and_custom_scope(tmp_path):
    """§63: presets serve the precomputed views; a custom scope
    aggregates the fact table at request time; invalid dates and
    unknown tournaments clamp to empty, never an error."""
    import json as _json
    from datetime import datetime, timedelta, timezone

    from vpredict.data.schema import Match, MapResult, PlayerMapStats
    from vpredict.data.trends import build_trends_bundle
    from vpredict.serving.api import create_app

    now = datetime(2026, 8, 8, tzinfo=timezone.utc)

    def _players(k):
        return [PlayerMapStats(name=f"p{i}", agent="Jett", kills=k,
                               fk=1, fd=0) for i in range(5)]

    def _m(i, days_ago, event):
        return Match(
            match_id=f"m{i}", start_ts=now - timedelta(days=days_ago),
            status="completed", best_of=3, event=event, series="s",
            winner="team1", team1_id="A", team1_name="Team A",
            team2_id="B", team2_name="Team B",
            maps=[MapResult(game_id="g", map_name="Bind", index=1,
                            team1_score=13, team2_score=7, rounds=[],
                            team1_players=_players(15),
                            team2_players=_players(10))])

    ms = ([_m(i, 5 + i, "Cup Alpha Group Stage: Week 1")
           for i in range(6)]
          + [_m(90 + i, 400 + i, "Cup Beta Group Stage: Week 1")
             for i in range(6)])
    table, views = build_trends_bundle(ms, now=now)
    proc = tmp_path / "processed"
    proc.mkdir(parents=True)
    (proc / "trends_rows.json").write_text(_json.dumps(table))
    (proc / "trends.json").write_text(_json.dumps(views))
    client = TestClient(create_app(data_dir=tmp_path))

    d = client.get("/api/trends").json()
    assert d["view"]["scope"] == {"preset": "all"}
    assert d["view"]["n_teams"] == 2
    assert {t["name"] for t in d["tournaments"]} == {"Cup Alpha",
                                                     "Cup Beta"}

    d = client.get("/api/trends?preset=current_form").json()
    assert d["view"]["scope"] == {"preset": "current_form"}
    # Cup Beta teams are 400+ days stale -> current form hides nothing
    # here (same two team ids play both), but the window caps maps at 10.
    assert all(t["n_window"] <= 10 for t in d["view"]["teams"])

    d = client.get("/api/trends?event=Cup+Beta").json()
    assert d["view"]["scope"]["event"] == "Cup Beta"
    assert all(t["n_window"] == 6 for t in d["view"]["teams"])

    d = client.get("/api/trends?from=2026-07-28").json()
    assert d["view"]["n_teams"] == 2
    assert all(t["n_window"] == 6 for t in d["view"]["teams"])
    # A scope holding fewer than TRENDS_SCOPE_MIN_MAPS per team lists
    # nobody: thresholds are visible, small samples are not estimated.
    d = client.get("/api/trends?from=2026-08-02").json()
    assert d["view"]["n_teams"] == 0

    d = client.get("/api/trends?from=notadate&event=No+Such+Cup").json()
    assert d["view"]["n_teams"] == 0             # clamped empty, no 4xx


def test_odds_ingest_gates_unpriceable_rows(tmp_path, monkeypatch):
    """ASSUMPTIONS §65: §58's priceable rule applies at every door. A
    suspended (0.0) price pushed through the ingest endpoint is counted
    and dropped, never appended — which also stops --push-log heals from
    re-importing pre-gate rows."""
    from fastapi.testclient import TestClient
    from vpredict.serving.api import create_app
    monkeypatch.setenv("VPREDICT_INGEST_TOKEN", "s3cret")
    c = TestClient(create_app(data_dir=tmp_path))
    base = {"captured_at": "2026-08-08T10:00:00+00:00",
            "source": "pinnacle", "capture_kind": "freeze",
            "market": "series_moneyline", "line": None,
            "book_event_id": "e1", "book_home": "A", "book_away": "B",
            "book_start_ts": "2026-08-09T10:00:00+00:00",
            "match_id": "m1", "book_home_is_team1": True,
            "link_method": "exact"}
    items = [dict(base, price_home=0.0, price_away=0.0),
             dict(base, book_event_id="e2", price_home=1.8,
                  price_away=2.0)]
    r = c.post("/api/ingest/odds", json={"captures": items},
               headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    got = r.json()
    assert got["unpriceable"] == 1 and got["appended"] == 1
    log = (tmp_path / "odds" / "odds.jsonl").read_text()
    assert log.count("\n") == 1 and '"price_home":1.8' in log
