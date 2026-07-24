"""Calibration monitor (ASSUMPTIONS §13): Wilson interval, Spiegelhalter Z,
threshold semantics, extrapolation flagging — drift detection only."""
from __future__ import annotations

import pytest

from vpredict.evaluation.calibration import (monitor_report, spiegelhalter_z,
                                             wilson_interval)


def _rows(p, y, n, event="VCT Masters"):
    return [{"p_model": p, "team1_won": y, "event": event}] * n


def test_wilson_known_value():
    lo, hi = wilson_interval(8, 10)
    assert lo == pytest.approx(0.4901, abs=2e-3)
    assert hi == pytest.approx(0.9433, abs=2e-3)
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_spiegelhalter_zero_for_exactly_calibrated_construction():
    ps = [0.7] * 100
    ys = [1] * 70 + [0] * 30
    assert spiegelhalter_z(ps, ys) == pytest.approx(0.0, abs=1e-12)


def test_spiegelhalter_sign_for_overconfident_favourites():
    z = spiegelhalter_z([0.9] * 60, [0] * 60)   # said 0.9, never happened
    assert z is not None and abs(z) > 3


def test_thresholds_insufficient_reported_actionable():
    r = monitor_report(_rows(0.60, 1, 29))
    (only,) = r["buckets"].values()
    assert only["status"] == "insufficient"
    r = monitor_report(_rows(0.60, 1, 30))
    (only,) = r["buckets"].values()
    assert only["status"] == "reported"          # CI shown, no action yet
    # n=120, mean_p=0.60, observed=1.0 -> Wilson CI excludes 0.60 -> DRIFT
    r = monitor_report(_rows(0.60, 1, 120))
    (only,) = r["buckets"].values()
    assert only["status"] == "DRIFT"
    # n=120 at 60% observed matches mean_p -> ok
    rows = _rows(0.60, 1, 72) + _rows(0.60, 0, 48)
    (only,) = monitor_report(rows)["buckets"].values()
    assert only["status"] == "ok"


def test_extrapolation_cells_are_separate_and_counted():
    rows = _rows(0.10, 0, 5) + _rows(0.95, 1, 7) + _rows(0.5, 1, 3)
    r = monitor_report(rows)
    assert r["extrapolation_count"] == 12
    assert "extrapolation_low" in r["buckets"]
    assert "extrapolation_high" in r["buckets"]


def test_per_tier_split_uses_classifier():
    rows = _rows(0.6, 1, 40, event="VCT Champions") + \
           _rows(0.6, 0, 40, event="Game Changers NA")
    r = monitor_report(rows, tier_of=lambda e: "gc" if "Changers" in e
                       else "t1")
    assert set(r["tiers"]) == {"gc", "t1"}


def test_probabilities_are_never_modified():
    rows = _rows(0.60, 1, 50)
    r = monitor_report(rows)
    (only,) = r["buckets"].values()
    assert only["mean_p"] == 0.60                # reported, untouched
