"""Hypothetical unit tracker (ASSUMPTIONS §59).

Answers one question the raw win rate cannot: once stakes are sized to
edge, do the graded picks win IN AGGREGATE? Imaginary units only — no
dollars, no bankroll, no compounding. Stakes come from quarter Kelly on a
fixed notional with two clamps so a single outlier EV cannot dominate:

    full Kelly fraction  f* = (d*p - 1) / (d - 1) = EV / (d - 1)
    stake_units = min(FRACTION * NOTIONAL * min(EV, EV_CLIP) / (d - 1),
                      STAKE_CAP)                    stakes only when EV > 0
    settle: win -> +stake * (d - 1),  loss -> -stake

Eligibility mirrors the EV validation gate exactly: graded moneyline
picks with clean EV methodology (no extrapolation-band picks, no totals —
the same exclusions the gate applies), and only matches starting on or
after UNIT_TRACKER_START_TS: entries frozen before the LOG-59 capture fix
may be close-reused, and a tracker seeded on possibly-phantom entry
prices could never be trusted. A flat 1-unit line on the identical pick
set ships beside it so sizing effects and pick quality stay separable.
The tracker carries the SAME provisional status as the EV gate until
EV_MIN_GRADED_PICKS graded EV-clean picks exist.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import config


def _parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def stake_units(ev: float, price: float) -> float:
    """Clamped quarter-Kelly stake in units for a decimal price. 0 when
    the pick has no positive edge or the price is degenerate."""
    if price <= 1.0 or ev <= 0.0:
        return 0.0
    sized_ev = min(ev, config.UNIT_TRACKER_EV_CLIP)
    stake = (config.UNIT_TRACKER_KELLY_FRACTION
             * config.UNIT_TRACKER_NOTIONAL_UNITS
             * sized_ev / (price - 1.0))
    return round(min(stake, config.UNIT_TRACKER_STAKE_CAP_UNITS), 4)


def compute_unit_tracker(picks: list[dict], gate: dict) -> dict:
    """Aggregate the tracker over already-annotated picks (ev_excluded must
    be set by the caller, as build_markets_report does)."""
    start = _parse_ts(config.UNIT_TRACKER_START_TS)
    rows = []
    for p in picks:
        if not p.get("graded") or p.get("won") is None:
            continue
        if p.get("market") != "series_moneyline":
            continue
        if p.get("ev_excluded") is not None:
            continue
        if _parse_ts(p["start_ts"]) < start:
            continue
        price = float(p["price_entry"])
        ev = float(p["ev_pct"]) / 100.0
        stake = stake_units(ev, price)
        if stake <= 0.0:
            continue
        pnl = stake * (price - 1.0) if p["won"] else -stake
        flat = (price - 1.0) if p["won"] else -1.0
        rows.append({
            "match_id": p["match_id"], "match": p["match"],
            "selection": p["selection"], "start_ts": p["start_ts"],
            "price_entry": price, "ev_pct": p["ev_pct"],
            "stake_units": stake, "pnl_units": round(pnl, 4),
            "won": p["won"],
        })
    rows.sort(key=lambda r: r["start_ts"])
    staked = sum(r["stake_units"] for r in rows)
    pnl = sum(r["pnl_units"] for r in rows)
    flat_pnl = sum((r["price_entry"] - 1.0) if r["won"] else -1.0
                   for r in rows)
    return {
        "start_ts": config.UNIT_TRACKER_START_TS,
        "params": {
            "kelly_fraction": config.UNIT_TRACKER_KELLY_FRACTION,
            "notional_units": config.UNIT_TRACKER_NOTIONAL_UNITS,
            "ev_clip": config.UNIT_TRACKER_EV_CLIP,
            "stake_cap_units": config.UNIT_TRACKER_STAKE_CAP_UNITS,
        },
        "n_staked": len(rows),
        "n_wins": sum(r["won"] for r in rows),
        "units_staked": round(staked, 2),
        "units_pnl": round(pnl, 2),
        "roi_pct": round(100.0 * pnl / staked, 2) if staked > 0 else None,
        "flat_pnl_units": round(flat_pnl, 2),
        # Same gate as EV validation: hypothetical AND provisional until it
        # passes; the flag never clears on the tracker's own sample size.
        "provisional": not gate.get("ev_validated", False),
        "picks": rows,
    }
