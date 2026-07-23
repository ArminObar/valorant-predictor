"""Ledger integrity: the freeze rule, first-prediction-wins, grading, metrics."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from vpredict.data.schema import Match
from vpredict.serving.ledger import Ledger

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def _mk(tmp_path):
    return Ledger(tmp_path / "ledger.sqlite")


def _insert(led, mid="m1", start=None, p_model=0.7, p_elo=0.6, now=NOW):
    return led.insert_prediction(
        match_id=mid, start_ts=start or (NOW + timedelta(hours=2)),
        team1="a", team2="b", team1_name="A", team2_name="B",
        event="E", best_of=3, p_model=p_model, p_elo=p_elo,
        model_version="v1", now=now)


def test_freeze_margin_rejects_late_predictions(tmp_path):
    led = _mk(tmp_path)
    # 2 minutes before start < 5-minute margin -> refused, nothing stored.
    assert _insert(led, start=NOW + timedelta(minutes=2)) == "too_late"
    assert led.rows() == []
    # 6 minutes before start -> accepted.
    assert _insert(led, start=NOW + timedelta(minutes=6)) == "inserted"


def test_first_prediction_is_frozen(tmp_path):
    led = _mk(tmp_path)
    assert _insert(led, p_model=0.7) == "inserted"
    # A later call (even a "better" model) cannot overwrite the first.
    assert _insert(led, p_model=0.99) == "frozen"
    rows = led.rows()
    assert len(rows) == 1 and rows[0]["p_model"] == 0.7


def _completed(mid: str, winner: str) -> Match:
    return Match(match_id=mid, start_ts=NOW - timedelta(hours=3),
                 status="completed", winner=winner,
                 team1_name="A", team2_name="B")


def test_grading_and_summary_math(tmp_path):
    led = _mk(tmp_path)
    _insert(led, mid="m1", p_model=0.8, p_elo=0.5)   # team1 wins -> correct
    _insert(led, mid="m2", p_model=0.6, p_elo=0.5)   # team2 wins -> wrong
    _insert(led, mid="m3", p_model=0.5, p_elo=0.5)   # never completes
    n = led.grade([_completed("m1", "team1"), _completed("m2", "team2")])
    assert n == 2
    s = led.summary()
    assert s["n_graded"] == 2 and s["n_pending"] == 1
    # Hand-computed: LL = -(ln .8 + ln .4)/2 ; acc = 1/2.
    want_ll = -(math.log(0.8) + math.log(0.4)) / 2
    assert math.isclose(s["model"]["log_loss"], want_ll, rel_tol=1e-9)
    assert s["model"]["accuracy"] == 0.5
    assert math.isclose(s["model"]["brier"],
                        ((0.8 - 1) ** 2 + (0.6 - 0) ** 2) / 2, rel_tol=1e-9)
    # Grading is idempotent.
    assert led.grade([_completed("m1", "team1")]) == 0


def test_grade_ignores_unfinished_matches(tmp_path):
    led = _mk(tmp_path)
    _insert(led, mid="m9")
    live = Match(match_id="m9", start_ts=NOW, status="live",
                 team1_name="A", team2_name="B")
    assert led.grade([live]) == 0
    assert led.summary()["n_graded"] == 0
