"""Roster-continuity live checkpoint (ASSUMPTIONS §70).

Measures the rev-5 roster family on the population it exists for:
graded low-history predictions made after the family went live,
against the p_elo logged at the same moment (the comparator that
cannot be recomputed favorably later). The schedule and the single
primary criterion were pinned in §70 before any qualifying data
existed, and the tool enforces its own discipline: below the first
registered n it withholds the metrics entirely — a number nobody has
seen cannot steer anyone — and it never renders a verdict before the
registered decision n.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .. import config
from ..evaluation.tiers import classify_tier
from ..modeling.train import ll


def _ts(v) -> datetime:
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _metrics(rows: list[dict]) -> dict:
    y = np.array([float(r["team1_won"]) for r in rows])
    pm = np.array([float(r["p_model"]) for r in rows])
    pe = np.array([float(r["p_elo"]) for r in rows])
    return {"n": len(rows),
            "ll_model": round(ll(y, pm), 4),
            "ll_elo": round(ll(y, pe), 4),
            "brier_model": round(float(np.mean((pm - y) ** 2)), 4),
            "brier_elo": round(float(np.mean((pe - y) ** 2)), 4),
            "acc_model": round(float(np.mean((pm >= 0.5) == (y == 1))), 4),
            "acc_elo": round(float(np.mean((pe >= 0.5) == (y == 1))), 4)}


def checkpoint(rows: list[dict], since: str | None = None,
               first_n: int | None = None,
               decision_n: int | None = None) -> dict:
    """Pure over ledger-row dicts; reads nothing, writes nothing."""
    since_ts = _ts(since or config.ROSTER_LIVE_SINCE)
    first_n = first_n or config.ROSTER_CHECKPOINT_FIRST_N
    decision_n = decision_n or config.ROSTER_CHECKPOINT_DECISION_N

    era = [r for r in rows
           if r.get("graded") and r.get("team1_won") is not None
           and _ts(r["made_at"]) >= since_ts]
    lowh = [r for r in era if r.get("low_history")]
    estab = [r for r in era if not r.get("low_history")]

    out = {"since": since_ts.isoformat(),
           "first_n": first_n, "decision_n": decision_n,
           "n": len(lowh), "n_established": len(estab)}
    if len(lowh) < first_n:
        out["phase"] = "accumulating"
        return out

    out["slice"] = _metrics(lowh)
    out["established"] = _metrics(estab) if estab else {"n": 0}
    tiers: dict = {}
    for t in sorted({classify_tier(r.get("event") or "") for r in lowh}):
        sub = [r for r in lowh
               if classify_tier(r.get("event") or "") == t]
        tiers[t] = _metrics(sub)
    out["by_tier"] = tiers
    out["model_versions"] = sorted({r.get("model_version") or "?"
                                    for r in lowh})
    if len(lowh) < decision_n:
        out["phase"] = "directional"
        return out
    out["phase"] = "decision"
    out["primary_met"] = out["slice"]["ll_model"] < out["slice"]["ll_elo"]
    return out


def render(rep: dict) -> str:
    lines = [
        "=" * 70,
        "ROSTER-CONTINUITY LIVE CHECKPOINT (ASSUMPTIONS 70)",
        f"  era boundary: predictions made at/after {rep['since']}",
        "  (provisional-conservative until the 0082 deploy verification"
        " is reported)",
        f"  qualifying low-history graded: {rep['n']}"
        f"   established (context): {rep['n_established']}",
    ]
    if rep["phase"] == "accumulating":
        lines += [
            f"  phase: ACCUMULATING — below the first read at "
            f"n={rep['first_n']} (decision at n={rep['decision_n']}).",
            "  Metrics withheld by 70: repeated small-n peeks invite",
            "  anchoring, and a number nobody has seen cannot steer"
            " anyone.",
        ]
        return "\n".join(lines)

    def _tbl(name, m):
        return (f"  {name:<22s} n={m['n']:<4d} "
                f"LL {m['ll_model']} vs elo {m['ll_elo']}   "
                f"Brier {m['brier_model']} vs {m['brier_elo']}   "
                f"acc {m['acc_model']} vs {m['acc_elo']}")

    lines.append(_tbl("low-history slice:", rep["slice"]))
    if rep["established"].get("n"):
        lines.append(_tbl("established (context):", rep["established"]))
    for t, m in rep["by_tier"].items():
        lines.append(_tbl(f"  tier {t}:", m))
    lines.append(f"  model versions in slice: "
                 f"{', '.join(rep['model_versions'])}")
    if rep["phase"] == "directional":
        lines += [
            f"  phase: DIRECTIONAL — no verdict before "
            f"n={rep['decision_n']} (70).",
        ]
    else:
        met = rep["primary_met"]
        lines += [
            f"  phase: DECISION READ (n >= {rep['decision_n']})",
            f"  PRIMARY (model LL < Elo LL on the slice): "
            f"{'MET' if met else 'NOT MET'}",
            "  Reminder pinned in 70: the ablation remains the primary",
            "  evidence; this read is a serving-path sanity check."
            " Phase 2 stays an owner call.",
        ]
    return "\n".join(lines)
