"""Calibrated-probability bounds (LOG entries 31-32).

Two saturation modes were observed in the field: isotonic freshly past its
admission gate plateaus AT 0/1 (July 2025, the walk-forward backtest), and
Platt on a tiny separable validation slice becomes a step function whose
tails are 0/1 to float precision (the patch-0019 fixture failing on the
owner's Mac with p_model == 1.0 exactly). The hardening is two independent
bounds: calibrator transforms are clipped to [CAL_OUTPUT_CLIP, 1-...], and
published probabilities are clamped one rounding-ulp inside (0, 1) —
because series aggregation can push map-clipped probabilities back within
rounding distance of 1.0 (a Bo5 of 0.995s is 0.999999).
"""
from __future__ import annotations

import numpy as np

from vpredict import config
from vpredict.modeling.predict import _pub
from vpredict.modeling.series import series_prob
from vpredict.modeling.train import (IsotonicCalibrator, PlattCalibrator,
                                     fit_calibrator)

LO, HI = config.CAL_OUTPUT_CLIP, 1 - config.CAL_OUTPUT_CLIP


def test_platt_step_function_is_bounded():
    # Perfectly separable tiny validation slice -> exploding slope. The
    # transform must still never claim more than the clip allows.
    p_val = np.array([0.30, 0.35, 0.40, 0.60, 0.65, 0.70])
    y_val = np.array([0, 0, 0, 1, 1, 1])
    cal = PlattCalibrator().fit(p_val, y_val)
    out = cal.transform(np.linspace(0.001, 0.999, 999))
    assert out.min() >= LO and out.max() <= HI


def test_isotonic_plateaus_are_bounded():
    # Pure extreme bins make isotonic's end plateaus sit at exactly 0/1
    # without the clip.
    rng = np.random.default_rng(0)
    p_val = np.sort(rng.uniform(0.05, 0.95, 200))
    y_val = (p_val > 0.5).astype(int)          # perfectly pure ends
    cal = IsotonicCalibrator().fit(p_val, y_val)
    out = cal.transform(np.linspace(0.0, 1.0, 1001))
    assert out.min() >= LO and out.max() <= HI


def test_fit_calibrator_selection_respects_bounds():
    p_val = np.array([0.2, 0.3, 0.7, 0.8] * 3)
    y_val = np.array([0, 0, 1, 1] * 3)
    _, cal, _ = fit_calibrator(p_val, y_val)
    out = cal.transform(np.array([1e-9, 0.5, 1 - 1e-9]))
    assert out.min() >= LO and out.max() <= HI


def test_publish_clamp_never_emits_certainty():
    lo = 10.0 ** -config.PROB_DECIMALS
    assert _pub(1.0) == 1.0 - lo
    assert _pub(0.0) == lo
    assert _pub(0.99999) == 1.0 - lo           # rounds to 1.0, clamped back
    assert _pub(0.6431) == 0.6431              # in-band values untouched


def test_bo5_compounding_cannot_round_to_one():
    # The reason the publish clamp exists at the series boundary: a Bo5 of
    # map-clipped 0.995s aggregates to 0.999999 -> rounds to 1.0000.
    s = series_prob([HI] * 5)
    assert s > 1 - 10.0 ** -config.PROB_DECIMALS    # the hazard is real
    assert _pub(s) == 1 - 10.0 ** -config.PROB_DECIMALS
