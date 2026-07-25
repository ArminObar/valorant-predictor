"""The publish gate for the recent-window summary (ASSUMPTIONS §22).

publish_results.py may only MOVE an evaluate.py artifact, and only a
valid one: synthetic-watermarked or structurally incomplete summaries are
refused with named reasons. These tests pin the gate itself."""
from __future__ import annotations

from vpredict.evaluation.results_summary import validate_summary


def _valid() -> dict:
    return {"generated_at": "2026-07-25T00:00:00+00:00",
            "source": "scripts/evaluate.py", "synthetic": False,
            "store": {}, "split": {},
            "selected": {"name": "lr", "calibration": "platt"},
            "map": {"model": {"log_loss": 0.66}, "elo": {"log_loss": 0.67}},
            "series": {"model": {"log_loss": 0.65},
                       "elo": {"log_loss": 0.66}},
            "per_tier": []}


def test_valid_summary_passes():
    assert validate_summary(_valid()) == []


def test_synthetic_summary_is_refused():
    r = _valid()
    r["synthetic"] = True
    problems = validate_summary(r)
    assert any("synthetic" in p for p in problems)


def test_missing_keys_and_metrics_are_named():
    r = _valid()
    del r["per_tier"]
    r["series"]["elo"] = {}                       # log_loss gone
    problems = validate_summary(r)
    assert any("per_tier" in p for p in problems)
    assert any("series.elo.log_loss" in p for p in problems)
    assert validate_summary("nonsense") == ["summary is not a JSON object"]
