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


def test_placeholder_names_backfilled_and_not_scored(tmp_path):
    """A TBD-vs-TBD bracket slot: names backfill at grade time (display
    metadata, ASSUMPTIONS §15), the frozen probabilities stand, and the
    headline metrics exclude it via the low-history scoring rule."""
    from vpredict.data.schema import Match
    from vpredict.serving.ledger import Ledger
    from datetime import datetime, timedelta, timezone

    led = Ledger(tmp_path / "l.sqlite")
    start = datetime.now(timezone.utc) + timedelta(hours=2)
    led.insert_prediction(
        match_id="m1", start_ts=start, team1="tbd", team2="tbd",
        team1_name="TBD", team2_name="TBD", event="Cup", best_of=3,
        p_model=0.5843, p_elo=0.5, model_version="t", low_history=True)
    done = Match(match_id="m1", start_ts=start, status="completed",
                 best_of=3, team1_id="a", team1_name="Alpha",
                 team2_id="b", team2_name="Beta", winner="team1",
                 team1_maps=2, team2_maps=0)
    assert led.grade([done]) == 1
    row = led.rows(graded=True)[0]
    assert (row["team1_name"], row["team2_name"]) == ("Alpha", "Beta")
    assert row["p_model"] == 0.5843          # frozen probability untouched
    s = led.summary()
    assert s["n_graded"] == 1 and s["n_low_history"] == 1
    assert s["n_scored"] == 0 and s["model"] is None
    led.close()


def test_self_collided_fixture_is_never_predicted(tmp_path):
    """run_predictions skips fixtures whose team keys collide (TBD vs TBD:
    the model would be predicting a team against itself)."""
    import pandas as pd
    from vpredict.data.schema import Match
    from vpredict.serving.ledger import Ledger
    from vpredict.modeling.predict import run_predictions
    from datetime import datetime, timedelta, timezone

    class _Bundle(dict):
        pass
    # A fake bundle is unnecessary: the guard runs before any model work,
    # so an empty upcoming list after filtering must short-circuit cleanly.
    led = Ledger(tmp_path / "l.sqlite")
    start = datetime.now(timezone.utc) + timedelta(hours=2)
    tbd = Match(match_id="x", start_ts=start, status="upcoming", best_of=3,
                team1_name="TBD", team2_name="TBD")
    out = run_predictions({"version": "t"}, [], [tbd], led,
                          json_path=tmp_path / "up.json")
    assert out["skipped_placeholder"] == 1 and out["inserted"] == 0
    led.close()
