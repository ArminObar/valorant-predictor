"""Calibration monitor over the graded ledger (ASSUMPTIONS §13).

Drift DETECTION, never per-match correction: bucketed predicted-vs-observed
rates per bucket and per tier, with hard thresholds — a cell is reported at
n >= 30, actionable only at n >= 100 AND a Wilson 95% interval excluding the
cell's mean predicted probability. The early warning with less data is one
global Spiegelhalter Z over all graded rows (interpretable from roughly
50-100 rows). Predictions outside the calibration-validated series range
(p < 0.15 or p > 0.88) are counted as EXTRAPOLATION and excluded from the
inner cells; the probabilities themselves are never modified anywhere.

Stdlib + sqlite only, so the API endpoint stays import-light.
"""
from __future__ import annotations

import math

REPORT_MIN_N = 30
ACT_MIN_N = 100
EXTRAP_LO = 0.15
EXTRAP_HI = 0.88
INNER_EDGES = [0.15, 0.35, 0.50, 0.65, 0.88]   # 4 inner cells


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials."""
    if n <= 0:
        return (0.0, 1.0)
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def spiegelhalter_z(ps: list[float], ys: list[int]) -> float | None:
    """Spiegelhalter's calibration Z: 0 for perfect calibration, positive
    when outcomes systematically undershoot the stated probabilities."""
    num = sum((y - p) * (1 - 2 * p) for p, y in zip(ps, ys))
    den = sum(((1 - 2 * p) ** 2) * p * (1 - p) for p in ps)
    if den <= 0:
        return None
    return num / math.sqrt(den)


def _bucket_of(p: float) -> str:
    if p < EXTRAP_LO:
        return "extrapolation_low"
    if p > EXTRAP_HI:
        return "extrapolation_high"
    for lo, hi in zip(INNER_EDGES[:-1], INNER_EDGES[1:]):
        if p <= hi:
            return f"[{lo:.2f},{hi:.2f}]"
    return f"[{INNER_EDGES[-2]:.2f},{INNER_EDGES[-1]:.2f}]"


def _cell_report(rows: list[tuple[float, int]]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0, "status": "empty"}
    mean_p = sum(p for p, _ in rows) / n
    k = sum(y for _, y in rows)
    obs = k / n
    lo, hi = wilson_interval(k, n)
    if n < REPORT_MIN_N:
        status = "insufficient"
    elif n < ACT_MIN_N:
        status = "reported"
    elif not (lo <= mean_p <= hi):
        status = "DRIFT"
    else:
        status = "ok"
    return {"n": n, "mean_p": round(mean_p, 4), "observed": round(obs, 4),
            "wilson95": [round(lo, 4), round(hi, 4)], "status": status}


def monitor_report(graded_rows: list[dict],
                   tier_of=None) -> dict:
    """graded_rows: dicts with p_model, team1_won, event (ledger rows).
    tier_of: optional callable event -> tier name."""
    pairs = [(float(r["p_model"]), int(r["team1_won"])) for r in graded_rows]
    out: dict = {"n_graded": len(pairs)}
    z = spiegelhalter_z([p for p, _ in pairs], [y for _, y in pairs]) \
        if pairs else None
    out["spiegelhalter_z"] = None if z is None else round(z, 3)
    out["spiegelhalter_note"] = (
        "global early warning; interpret from ~50-100 graded rows")

    def bucketed(rows: list[tuple[float, int]]) -> dict:
        cells: dict[str, list] = {}
        for p, y in rows:
            cells.setdefault(_bucket_of(p), []).append((p, y))
        return {name: _cell_report(rs) for name, rs in sorted(cells.items())}

    out["buckets"] = bucketed(pairs)
    out["extrapolation_count"] = sum(
        1 for p, _ in pairs if p < EXTRAP_LO or p > EXTRAP_HI)
    if tier_of is not None:
        by_tier: dict[str, list] = {}
        for r, pr in zip(graded_rows, pairs):
            by_tier.setdefault(tier_of(r.get("event") or ""), []).append(pr)
        out["tiers"] = {t: bucketed(rs) for t, rs in sorted(by_tier.items())}
    return out
