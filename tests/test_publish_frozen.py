"""The published upcoming payload serves the LEDGER, not the live model.

Field finding (LOG entry 44): /api/upcoming published each cycle's fresh
model output while the detail page served the frozen ledger row, so the two
disagreed on a live page by up to 0.23. These tests pin the fix:

1. once frozen, the published p_model/p_elo equal the ledger row even when
   the current model would say something very different;
2. a match inside the freeze margin with no row is absent from the payload
   (an uncalled match must never display as a call);
3. when every match is frozen and carried, the engine is not consulted and
   the payload still rewrites with a fresh generated_at;
4. reschedules display the listing's start_ts while the call stays frozen.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from vpredict import config
from vpredict.data.schema import Match
from vpredict.modeling import predict as predict_mod
from vpredict.serving.ledger import Ledger

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
BUNDLE = {"version": "test-bundle"}


def _match(mid: str, start: datetime, t1="red", t2="blu") -> Match:
    return Match(match_id=mid, start_ts=start, status="upcoming",
                 team1_id=t1, team2_id=t2, team1_name=t1.upper(),
                 team2_name=t2.upper(), event="Synthetic Cup",
                 series="Group Stage", best_of=3, synthetic=True)


def _fake_engine(p_model: float, calls: list | None = None):
    def fake(bundle, history, upcoming, now=None):
        if calls is not None:
            calls.append([um.match_id for um in upcoming])
        return [{
            "match_id": um.match_id, "start_ts": um.start_ts.isoformat(),
            "event": um.event, "series": um.series, "best_of": um.best_of,
            "team1": um.key_team("team1"), "team2": um.key_team("team2"),
            "team1_name": um.team1_name, "team2_name": um.team2_name,
            "p_model": p_model, "p_elo": 0.55,
            "maps_dist": {"2": 0.6, "3": 0.4},
            "per_map": {"Ascent": p_model}, "per_map_elo": {"Ascent": 12.0},
            "pool": ["Ascent"], "low_history": False,
            "model_version": bundle.get("version", "unknown"),
        } for um in upcoming]
    return fake


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path)
    led = Ledger(tmp_path / "ledger.sqlite")
    yield led, tmp_path / "upcoming_predictions.json"
    led.close()


def test_published_payload_equals_frozen_ledger(env, monkeypatch):
    led, jpath = env
    m = _match("m1", NOW + timedelta(hours=6))
    monkeypatch.setattr(predict_mod, "predict_upcoming", _fake_engine(0.60))
    predict_mod.run_predictions(BUNDLE, [], [m], led, now=NOW)
    # Same match, a drifted model an hour later.
    monkeypatch.setattr(predict_mod, "predict_upcoming", _fake_engine(0.90))
    c = predict_mod.run_predictions(
        BUNDLE, [], [m], led, now=NOW + timedelta(hours=1))
    got = json.loads(jpath.read_text())["predictions"][0]
    assert got["p_model"] == pytest.approx(0.60)
    assert got["p_elo"] == pytest.approx(0.55)
    assert c["frozen"] == 1 and c["inserted"] == 0
    row = led.rows(graded=None, limit=10)[0]
    assert got["p_model"] == pytest.approx(row["p_model"])


def test_uncalled_inside_margin_is_absent(env, monkeypatch):
    led, jpath = env
    late = _match("m2", NOW + timedelta(seconds=60))
    monkeypatch.setattr(predict_mod, "predict_upcoming", _fake_engine(0.70))
    c = predict_mod.run_predictions(BUNDLE, [], [late], led, now=NOW)
    payload = json.loads(jpath.read_text())
    assert payload["predictions"] == []
    assert c["too_late"] == 1
    assert led.rows(graded=None, limit=10) == []


def test_engine_skipped_when_all_frozen_and_carried(env, monkeypatch):
    led, jpath = env
    m = _match("m3", NOW + timedelta(hours=6))
    calls: list = []
    monkeypatch.setattr(predict_mod, "predict_upcoming",
                        _fake_engine(0.60, calls))
    predict_mod.run_predictions(BUNDLE, [], [m], led, now=NOW)
    t1 = json.loads(jpath.read_text())["generated_at"]

    def boom(*a, **k):
        raise AssertionError("engine consulted for a frozen, carried match")
    monkeypatch.setattr(predict_mod, "predict_upcoming", boom)
    predict_mod.run_predictions(
        BUNDLE, [], [m], led, now=NOW + timedelta(minutes=30))
    payload = json.loads(jpath.read_text())
    assert payload["generated_at"] != t1          # freshness still signaled
    assert payload["pool"] == ["Ascent"]          # carried, not dropped
    assert payload["predictions"][0]["per_map_elo"] == {"Ascent": 12.0}
    assert calls == [["m3"]]                      # engine ran exactly once


def test_reschedule_displays_listing_time_call_stays_frozen(env, monkeypatch):
    led, jpath = env
    m = _match("m4", NOW + timedelta(hours=6))
    monkeypatch.setattr(predict_mod, "predict_upcoming", _fake_engine(0.60))
    predict_mod.run_predictions(BUNDLE, [], [m], led, now=NOW)
    moved = _match("m4", NOW + timedelta(hours=9))
    predict_mod.run_predictions(
        BUNDLE, [], [moved], led, now=NOW + timedelta(hours=1))
    got = json.loads(jpath.read_text())["predictions"][0]
    assert got["start_ts"] == moved.start_ts.isoformat()
    assert got["p_model"] == pytest.approx(0.60)
