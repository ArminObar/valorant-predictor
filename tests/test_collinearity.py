"""Collinearity diagnostics: known-answer checks."""
import numpy as np
import pandas as pd

from vpredict.evaluation.collinearity import top_correlations, vif_table


def test_vif_flags_duplicated_feature():
    rng = np.random.default_rng(3)
    a = rng.normal(size=400)
    b = rng.normal(size=400)
    X = pd.DataFrame({"a": a, "b": b, "a_copy": a + rng.normal(0, 1e-6, 400)})
    v = vif_table(X).set_index("feature")["vif"]
    assert v["a"] > 1e6 and v["a_copy"] > 1e6      # near-duplicates explode
    assert v["b"] < 1.1                            # independent stays ~1


def test_vif_independent_features_near_one():
    rng = np.random.default_rng(4)
    X = pd.DataFrame(rng.normal(size=(500, 4)), columns=list("wxyz"))
    assert (vif_table(X)["vif"] < 1.1).all()


def test_top_correlations_orders_by_abs():
    rng = np.random.default_rng(5)
    a = rng.normal(size=300)
    X = pd.DataFrame({"a": a, "neg": -a + rng.normal(0, 0.1, 300),
                      "noise": rng.normal(size=300)})
    (f1, f2, v), *_ = top_correlations(X, k=1)
    assert {f1, f2} == {"a", "neg"} and v < -0.9
