"""De-vig methods for two-outcome (series winner) decimal prices.

Raw prices are stored append-only and never de-vigged at capture time;
these functions run at ANALYSIS time (ASSUMPTIONS §13). Shin is the primary
method, multiplicative the sensitivity column beside it — both are always
computed so the sensitivity is never silently dropped.

Background for the reader: a book's implied probabilities 1/odds sum to
more than 1 (the overround, the book's margin). Multiplicative de-vig
scales them to sum to 1 — it spreads the margin proportionally.
Shin (1992) models the margin as protection against informed bettors, which
puts relatively more of the margin on longshots; removing it therefore
shifts probability toward the favourite compared with multiplicative. The
gap between the two columns is itself information about how margin-model
sensitive a number is.
"""
from __future__ import annotations

import math


def implied(decimal_odds: list[float]) -> list[float]:
    """Raw implied probabilities 1/o (sum > 1 by the overround)."""
    if any(o <= 1.0 for o in decimal_odds):
        raise ValueError(f"decimal odds must be > 1.0, got {decimal_odds}")
    return [1.0 / o for o in decimal_odds]


def overround(decimal_odds: list[float]) -> float:
    """Booksum minus 1 — the margin. 0 means fair odds."""
    return sum(implied(decimal_odds)) - 1.0


def devig_multiplicative(decimal_odds: list[float]) -> list[float]:
    q = implied(decimal_odds)
    s = sum(q)
    return [x / s for x in q]


def _shin_probs(q: list[float], z: float, booksum: float) -> list[float]:
    return [
        (math.sqrt(z * z + 4.0 * (1.0 - z) * (qi * qi) / booksum) - z)
        / (2.0 * (1.0 - z))
        for qi in q
    ]


def devig_shin(decimal_odds: list[float], tol: float = 1e-12,
               max_iter: int = 200) -> list[float]:
    """Shin's method for k outcomes, solved by bisection on the insider
    fraction z in [0, 1). At z=0 the probabilities sum to booksum (>= 1) and
    the sum decreases monotonically in z, so bisection on (sum - 1) is
    robust. Fair odds (booksum == 1) return the implied probabilities
    unchanged.
    """
    q = implied(decimal_odds)
    booksum = sum(q)
    if booksum <= 1.0 + 1e-12:
        return [x / booksum for x in q]
    lo, hi = 0.0, 0.999999
    for _ in range(max_iter):
        z = 0.5 * (lo + hi)
        s = sum(_shin_probs(q, z, booksum))
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = z
        else:
            hi = z
    p = _shin_probs(q, 0.5 * (lo + hi), booksum)
    s = sum(p)
    return [x / s for x in p]   # exact renormalisation of the residual


def devig_both(decimal_odds: list[float]) -> dict:
    """The analysis-time record: raw implied plus both de-vig columns."""
    return {
        "implied": implied(decimal_odds),
        "overround": overround(decimal_odds),
        "shin": devig_shin(decimal_odds),
        "multiplicative": devig_multiplicative(decimal_odds),
    }
