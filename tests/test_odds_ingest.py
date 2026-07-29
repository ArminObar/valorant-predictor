"""/api/ingest/odds contract: validated, deduped, append-only.

The endpoint relaxes the old 'derived views only' ingest rule by exactly
one append-only surface (ASSUMPTIONS §42). These tests pin the walls:
schema validation rejects garbage without poisoning the log, duplicate
pushes are no-ops, appends accumulate rather than replace, and the token
guard applies.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from vpredict.serving.api import create_app

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _cap(kind="freeze", home="G2 Esports", away="Fnatic", src="pinnacle",
         at=NOW):
    return {"source": src, "capture_kind": kind,
            "market": "series_moneyline", "line": None,
            "book_event_id": "ev-1", "book_home": home, "book_away": away,
            "price_home": 1.83, "price_away": 2.01,
            "captured_at": at.isoformat()}


def _client(tmp_path, monkeypatch, token="tok"):
    if token is None:
        monkeypatch.delenv("VPREDICT_INGEST_TOKEN", raising=False)
    else:
        monkeypatch.setenv("VPREDICT_INGEST_TOKEN", token)
    return TestClient(create_app(data_dir=tmp_path))


def _post(c, payload, token="tok"):
    return c.post("/api/ingest/odds", json=payload,
                  headers={"Authorization": f"Bearer {token}"})


def test_rejects_without_token(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/ingest/odds", json={"captures": [_cap()]})
    assert r.status_code == 401
    assert not (tmp_path / "odds" / "odds.jsonl").exists()


def test_appends_validated_and_dedupes(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _post(c, {"captures": [_cap(), _cap()]})       # same record twice
    assert r.status_code == 200
    assert r.json() == {"received": 2, "appended": 1,
                        "duplicates": 1, "invalid": 0}
    # idempotent re-push
    r2 = _post(c, {"captures": [_cap()]})
    assert r2.json()["appended"] == 0 and r2.json()["duplicates"] == 1
    # a later close for the same fixture is a NEW record
    r3 = _post(c, {"captures": [_cap(kind="close",
                                     at=NOW + timedelta(hours=5))]})
    assert r3.json()["appended"] == 1
    lines = (tmp_path / "odds" / "odds.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    kinds = {json.loads(l)["capture_kind"] for l in lines}
    assert kinds == {"freeze", "close"}


def test_invalid_records_counted_never_written(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    bad = {"source": "pinnacle", "price_home": "not-a-price"}
    r = _post(c, {"captures": [bad, _cap()]})
    assert r.json()["invalid"] == 1 and r.json()["appended"] == 1
    lines = (tmp_path / "odds" / "odds.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1


def test_shape_guards(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert _post(c, {"nope": []}).status_code == 400
    assert _post(c, {"captures": [_cap()] * 2001}).status_code == 400
