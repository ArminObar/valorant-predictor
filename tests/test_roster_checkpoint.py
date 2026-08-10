"""§70's discipline, enforced by the tool itself: era and slice filters,
metrics against the logged comparator, and phase gating that withholds
numbers below the registered n and verdicts below the decision n."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vpredict.serving.roster_checkpoint import checkpoint, render

SINCE = datetime(2026, 8, 11, tzinfo=timezone.utc)


def _row(i, days_after=1.0, lowh=1, won=1, pm=0.7, pe=0.6, graded=1,
         event="VCT Americas"):
    return {"match_id": f"m{i}", "made_at":
            (SINCE + timedelta(days=days_after)).isoformat(),
            "p_model": pm, "p_elo": pe, "low_history": lowh,
            "graded": graded, "team1_won": won, "event": event,
            "model_version": "20260811-aaaa1111"}


def _rows(n, **kw):
    return [_row(i, **kw) for i in range(n)]


def test_below_first_n_withholds_all_metrics():
    rep = checkpoint(_rows(29), since=SINCE.isoformat())
    assert rep["phase"] == "accumulating" and rep["n"] == 29
    assert "slice" not in rep and "primary_met" not in rep
    assert "withheld" in render(rep).lower()


def test_directional_prints_numbers_but_never_a_verdict():
    rep = checkpoint(_rows(35), since=SINCE.isoformat())
    assert rep["phase"] == "directional"
    assert rep["slice"]["n"] == 35 and "primary_met" not in rep
    assert "no verdict" in render(rep).lower()


def test_decision_read_evaluates_the_single_primary_criterion():
    # Model calibrated better than Elo on winners -> lower log loss.
    winning = checkpoint(_rows(50, pm=0.8, pe=0.6),
                         since=SINCE.isoformat())
    assert winning["phase"] == "decision"
    assert winning["primary_met"] is True
    losing = checkpoint(_rows(50, pm=0.6, pe=0.8),
                        since=SINCE.isoformat())
    assert losing["primary_met"] is False
    assert "NOT MET" in render(losing)


def test_era_slice_and_grading_filters_hold():
    rows = (_rows(50) +
            _rows(10, days_after=-5) +          # pre-boundary: out
            _rows(10, lowh=0) +                 # established: context only
            _rows(10, graded=0, won=None))      # ungraded: out
    rep = checkpoint(rows, since=SINCE.isoformat())
    assert rep["n"] == 50 and rep["n_established"] == 10
    assert rep["established"]["n"] == 10


def test_per_tier_cells_print_with_their_n():
    rows = (_rows(30, event="VCT Americas")
            + [_row(100 + i, event="Game Changers NA") for i in range(20)])
    rep = checkpoint(rows, since=SINCE.isoformat())
    assert rep["phase"] == "decision"
    tier_ns = {t: m["n"] for t, m in rep["by_tier"].items()}
    assert sum(tier_ns.values()) == 50 and len(tier_ns) == 2
