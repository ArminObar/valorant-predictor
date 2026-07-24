"""Selection policy (LOG entry 24): deterministic pins, rolling-origin fold
scores, and the 1-SE hysteresis rule — including the regression the entry
demands: a retrain on identical data keeps the incumbent architecture."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vpredict.modeling.train import (choose_family, fit_lgbm,
                                     rolling_origin_scores, select_model)


def _toy(n=900, seed=3):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame({"a_diff": rng.normal(size=n),
                      "b_diff": rng.normal(size=n)})
    logit = 1.2 * X["a_diff"] - 0.6 * X["b_diff"]
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    return X, pd.Series(y)


def test_lightgbm_fit_is_deterministic_on_identical_data():
    X, y = _toy()
    a = fit_lgbm(X[:700], y[:700], X[700:], y[700:])
    b = fit_lgbm(X[:700], y[:700], X[700:], y[700:])
    assert a["val_ll"] == b["val_ll"]
    assert a["name"] == b["name"]


def test_rolling_scores_are_deterministic_and_per_family():
    X, y = _toy()
    s1 = rolling_origin_scores(X, y, n_train_matches=1000, n_folds=4)
    s2 = rolling_origin_scores(X, y, n_train_matches=1000, n_folds=4)
    assert set(s1) == {"logistic_regression", "lightgbm"}
    for fam in s1:
        assert np.array_equal(s1[fam], s2[fam])
        assert len(s1[fam]) == len(y) - int(round(len(y) * 0.5))


def test_hysteresis_keeps_incumbent_inside_one_se():
    rng = np.random.default_rng(0)
    base = rng.uniform(0.4, 0.9, size=400)
    tiny = 1e-4                                   # well inside noise
    scores = {"lightgbm": base, "logistic_regression": base - tiny}
    d = choose_family(scores, incumbent_family="lightgbm")
    assert d["chosen"] == "lightgbm" and d["switched"] is False
    assert d["margin_se"] is not None and d["margin_se"] <= 1.0


def test_hysteresis_switches_on_a_real_margin():
    rng = np.random.default_rng(0)
    base = rng.uniform(0.4, 0.9, size=400)
    scores = {"lightgbm": base, "logistic_regression": base - 0.05}
    d = choose_family(scores, incumbent_family="lightgbm")
    assert d["chosen"] == "logistic_regression" and d["switched"] is True
    assert d["margin_se"] > 1.0


def test_no_incumbent_is_plain_argmin():
    scores = {"lightgbm": np.array([0.6, 0.7]),
              "logistic_regression": np.array([0.5, 0.6])}
    d = choose_family(scores, incumbent_family=None)
    assert d["chosen"] == "logistic_regression"
    assert d["switched"] is None


def test_retrain_on_identical_data_keeps_architecture():
    """The LOG-24 regression at the decision layer: same data, same
    incumbent -> same choice, twice."""
    X, y = _toy()
    first = choose_family(
        rolling_origin_scores(X, y, n_train_matches=1000), None)
    again = choose_family(
        rolling_origin_scores(X, y, n_train_matches=1000), first["chosen"])
    assert again["chosen"] == first["chosen"]
    assert again["switched"] is False or again["rule"] == "incumbent is best"


def test_select_model_family_restriction():
    X, y = _toy()
    sel = select_model(X[:700], y[:700], X[700:], y[700:],
                       n_train_matches=1000,
                       families=["logistic_regression"])
    assert sel["name"].startswith("logistic_regression")
