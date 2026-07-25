"""SmoothIsotonicCalibrator (ASSUMPTIONS §21 option B) — the properties
that make it admissible, not its selection outcome.

What is pinned: monotone everywhere, exact at the step function's plateau
midpoints, genuinely smoother than the step (more distinct outputs on a
dense grid), bounded like every other calibrator, degenerate-safe, and
present in the menu under the same admission gate as step isotonic with
its score recorded. What is deliberately NOT pinned: which calibrator
wins validation — that is the selection rule's call on real data, and
hard-coding a winner here would be the cosmetic override §21 forbids.
"""
from __future__ import annotations

import numpy as np

from vpredict import config
from vpredict.modeling.train import (ISOTONIC_MIN_VAL, IsotonicCalibrator,
                                     SmoothIsotonicCalibrator,
                                     fit_calibrator)

RNG = np.random.default_rng(7)


def _val(n: int = 1200) -> tuple[np.ndarray, np.ndarray]:
    """Noisy but genuinely monotone validation set: P(y=1) rises with p."""
    p = RNG.uniform(0.05, 0.95, size=n)
    y = (RNG.uniform(size=n) < p).astype(int)
    return p, y


def test_monotone_and_bounded():
    p, y = _val()
    cal = SmoothIsotonicCalibrator().fit(p, y)
    grid = np.linspace(-0.2, 1.2, 4001)          # includes out-of-range
    out = cal.transform(grid)
    assert np.all(np.diff(out) >= -1e-12)        # monotone everywhere
    assert out.min() >= config.CAL_OUTPUT_CLIP - 1e-12
    assert out.max() <= 1 - config.CAL_OUTPUT_CLIP + 1e-12


def test_exact_at_plateau_midpoints_and_smoother_than_step():
    p, y = _val()
    step = IsotonicCalibrator().fit(p, y)
    smooth = SmoothIsotonicCalibrator().fit(p, y)
    # Interpolation passes exactly through (plateau mean input, level).
    inner = (smooth._my > config.CAL_OUTPUT_CLIP) & \
            (smooth._my < 1 - config.CAL_OUTPUT_CLIP)
    assert np.allclose(smooth.transform(smooth._mx[inner]),
                       smooth._my[inner], atol=1e-9)
    # The whole point (LOG 37): far more distinct outputs than the step
    # has levels, so nearby raw scores stop collapsing to one number.
    grid = np.linspace(p.min(), p.max(), 2000)
    n_step = len(np.unique(np.round(step.transform(grid), 6)))
    n_smooth = len(np.unique(np.round(smooth.transform(grid), 6)))
    assert n_smooth > 5 * n_step


def test_degenerate_single_plateau_falls_back_to_step():
    p = RNG.uniform(0.3, 0.7, size=50)
    y = np.zeros(50, dtype=int)                  # constant outcome
    cal = SmoothIsotonicCalibrator().fit(p, y)
    out = cal.transform(np.linspace(0, 1, 101))
    assert len(np.unique(out)) == 1              # one level, held
    assert out[0] >= config.CAL_OUTPUT_CLIP - 1e-12


def test_menu_gate_and_recorded_scores():
    p, y = _val(ISOTONIC_MIN_VAL)                # exactly at the gate
    name, cal, scores = fit_calibrator(p, y)
    assert set(scores) == {"platt", "isotonic", "smooth_isotonic"}
    assert name in scores and cal.name == name
    assert scores[name] == min(scores.values())  # standard rule, no thumb
    # Below the gate: Platt only — both isotonic variants share admission.
    p2, y2 = _val(ISOTONIC_MIN_VAL - 1)
    name2, _, scores2 = fit_calibrator(p2, y2)
    assert set(scores2) == {"platt"} and name2 == "platt"


def test_select_model_carries_the_calibration_decision():
    from vpredict.modeling.train import select_model
    n = max(ISOTONIC_MIN_VAL, 900)
    X = RNG.normal(size=(2 * n, 3))
    z = X @ np.array([1.2, -0.8, 0.5])
    y = (RNG.uniform(size=2 * n) < 1 / (1 + np.exp(-z))).astype(int)
    import pandas as pd
    Xdf = pd.DataFrame(X, columns=["f1", "f2", "f3"])
    sel = select_model(Xdf[:n], y[:n], Xdf[n:], y[n:], n_train_matches=100)
    assert set(sel["calibration_val_ll"]) == {
        "platt", "isotonic", "smooth_isotonic"}
    assert sel["cal_name"] in sel["calibration_val_ll"]
