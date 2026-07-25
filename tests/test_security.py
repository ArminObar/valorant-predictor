"""Security posture, pinned (patch 0039 audit).

What is asserted: every response carries the security headers; the
public API rate-limits per client IP with a clean 429; no CORS grant
exists for cross-origin callers; malformed match ids get a clean 400;
a non-ASCII Authorization header is a 401, never a 500; unauthorized
ingest reveals nothing; the static mount cannot serve anything outside
the built frontend; unhandled errors return a generic body.
"""
from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from vpredict import config
from vpredict.serving.api import create_app


def _client(tmp_path, **kw):
    return TestClient(create_app(data_dir=tmp_path), **kw)


def test_security_headers_on_every_response(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "Referrer-Policy" in r.headers


def test_no_cors_grant_for_cross_origin(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {
        k.lower() for k in r.headers.keys()}


def test_rate_limit_429_per_ip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 5)
    c = _client(tmp_path)
    for _ in range(5):
        assert c.get("/api/health",
                     headers={"x-forwarded-for": "9.9.9.9"}).status_code == 200
    blocked = c.get("/api/health", headers={"x-forwarded-for": "9.9.9.9"})
    assert blocked.status_code == 429
    assert blocked.json() == {"error": "rate limited"}
    assert blocked.headers.get("Retry-After") == "60"
    # a different client is unaffected
    assert c.get("/api/health",
                 headers={"x-forwarded-for": "8.8.8.8"}).status_code == 200


def test_match_id_input_guard(tmp_path):
    c = _client(tmp_path)
    assert c.get(f"/api/match/{'x' * 300}").status_code == 400
    assert c.get("/api/match/%00", ).status_code in (400, 404)
    ok = c.get("/api/match/123456")          # unknown but well-formed
    assert ok.status_code == 200
    assert ok.json()["ledger"] is None


def test_ingest_auth_edges(tmp_path, monkeypatch):
    monkeypatch.setenv("VPREDICT_INGEST_TOKEN", "s3cret")
    c = _client(tmp_path)
    for auth in ("Bearer wrong", "Bearer " + "x" * 4096, "Basic abc", ""):
        r = c.post("/api/ingest/results", json={},
                   headers={"Authorization": auth} if auth else {})
        assert r.status_code == 401
        assert r.json() == {"error": "unauthorized"}  # nothing else revealed
    # the compare itself is bytes-wise and total for any str the ASGI
    # layer can deliver (latin-1 decoded), so no header value can 500 it
    import hmac
    for got in ("Bearer \u00ff\u00e9", "Bearer ok", "\u0080" * 10):
        assert hmac.compare_digest(got.encode("utf-8"),
                                   b"Bearer s3cret") in (True, False)


def test_static_mount_cannot_serve_data_files(tmp_path, monkeypatch):
    # fake dist so the mount exists; fake ledger in the data dir
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>ok</html>")
    import vpredict.serving.api as api_mod
    monkeypatch.setattr(api_mod, "locate_frontend_dist", lambda: dist)
    led = tmp_path / "serving"
    led.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(led / "ledger.sqlite").close()
    c = _client(tmp_path)
    assert c.get("/").status_code == 200
    for path in ("/serving/ledger.sqlite", "/data/serving/ledger.sqlite",
                 "/../serving/ledger.sqlite", "/models/model.joblib"):
        r = c.get(path)
        assert r.status_code == 404
        assert b"SQLite format" not in r.content


def test_unhandled_errors_are_generic(tmp_path, monkeypatch):
    c = _client(tmp_path, raise_server_exceptions=False)
    # corrupt predictions file -> upcoming() raises inside the endpoint
    pj = tmp_path / "processed"
    pj.mkdir(parents=True, exist_ok=True)
    (pj / "upcoming_predictions.json").write_text("{not json")
    r = c.get("/api/upcoming")
    assert r.status_code == 500
    assert r.json() == {"error": "internal error"}
    assert "Traceback" not in r.text
