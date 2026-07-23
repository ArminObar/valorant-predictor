"""Collinearity diagnostics — a spec non-negotiable, and demonstrably
load-bearing here: the trained model distributes the shared team-strength
signal across correlated features (round share, side efficiencies, Elo), so
individual coefficients must never be read as marginal effects. This module
quantifies that with VIF (variance inflation factors, via auxiliary
regressions — no extra dependency) and the top pairwise correlations.

VIF_j = 1 / (1 - R²_j) where R²_j is from regressing feature j on all other
features. Conventional reading: > 5 notable, > 10 severe. High VIF does not
hurt *prediction* under regularization; it invalidates coefficient stories —
which is exactly the trap the report warns about.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


def vif_table(X: pd.DataFrame) -> pd.DataFrame:
    """VIF per column, descending. Constant columns report inf."""
    cols = list(X.columns)
    Xv = X.to_numpy(dtype=float)
    out: list[tuple[str, float]] = []
    for j, c in enumerate(cols):
        yj = Xv[:, j]
        if float(np.std(yj)) == 0.0:
            out.append((c, float("inf")))
            continue
        Xo = np.delete(Xv, j, axis=1)
        r2 = LinearRegression().fit(Xo, yj).score(Xo, yj)
        out.append((c, float("inf") if r2 >= 1.0 else 1.0 / (1.0 - r2)))
    return (pd.DataFrame(out, columns=["feature", "vif"])
            .sort_values("vif", ascending=False)
            .reset_index(drop=True))


def top_correlations(X: pd.DataFrame, k: int = 6) -> list[tuple[str, str, float]]:
    """The k largest |pairwise correlations| (signed values returned)."""
    corr = X.corr()
    pairs: list[tuple[str, str, float]] = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            v = corr.iloc[i, j]
            if pd.notna(v):
                pairs.append((cols[i], cols[j], float(v)))
    pairs.sort(key=lambda t: abs(t[2]), reverse=True)
    return pairs[:k]
