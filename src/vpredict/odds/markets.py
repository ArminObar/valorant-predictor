"""Markets & EV analysis — joins the frozen ledger with the odds log.

Every number here derives from two append-only records: the ledger row
frozen >=5 min before start (p_model, p_maps_dist) and the odds captures
(raw decimal prices at freeze and close). Nothing is recomputed with a
newer model, so the model-vs-market comparison can never be revised
favourably after the fact.

Definitions, recorded in ASSUMPTIONS §15:
  pick        per (match, market, line), on the headline source (first of
              config.ODDS_BOOK_PRIORITY that priced it): the side with the
              higher EV at the ENTRY (freeze) capture's raw price.
  EV          model_prob x decimal_odds - 1, at the raw entry price. The
              de-vigged probabilities (Shin primary, multiplicative
              sensitivity) are stored beside it for fair-value comparison,
              never blended into EV.
  CLV         entry_odds / close_odds - 1 on the pick's side; positive
              means the position beat the close. Requires a close capture.
  extrapolated model probability outside [EV_EXTRAPOLATION_LO, HI]: shown,
              labeled, excluded from EV/CLV aggregates.
  validated   EV aggregates carry an "unvalidated" flag until
              >= EV_MIN_GRADED_PICKS graded market-covered picks exist
              (pre-registered threshold; per-tier tables show regardless).

Scope (MODEL_CARD): series moneyline and map totals only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .. import config
from ..evaluation.tiers import classify_tier
from .devig import devig_both
from .schema import OddsCapture


def _entry_close(caps: list[OddsCapture]) -> tuple[OddsCapture, OddsCapture | None]:
    """Entry = earliest freeze capture (the public 'called at' price);
    close = latest close capture. A close-only market uses it for both."""
    caps = sorted(caps, key=lambda c: c.captured_at)
    freezes = [c for c in caps if c.capture_kind == "freeze"]
    closes = [c for c in caps if c.capture_kind == "close"]
    entry = freezes[0] if freezes else caps[0]
    close = closes[-1] if closes else None
    return entry, close


def _model_side_probs(row: dict, cap: OddsCapture) -> tuple[float, float] | None:
    """(p_home, p_away) in BOOK orientation for this market, from the FROZEN
    ledger row. None when the frozen record can't price the market (e.g. a
    totals capture for a row frozen before p_maps_dist existed)."""
    if cap.market == "series_moneyline":
        p1 = float(row["p_model"])
        if cap.book_home_is_team1 is None:
            return None
        return (p1, 1 - p1) if cap.book_home_is_team1 else (1 - p1, p1)
    if cap.market == "maps_total":
        raw = row.get("p_maps_dist")
        if not raw or cap.line is None:
            return None
        dist = {int(k): float(v) for k, v in json.loads(raw).items()}
        p_over = sum(v for k, v in dist.items() if k > cap.line)
        return p_over, 1 - p_over          # home=OVER, away=UNDER convention
    return None


def _grade(row: dict, cap: OddsCapture, side: str) -> bool | None:
    """Did the pick's side win? None while ungraded / ungradeable."""
    if not row.get("graded"):
        return None
    if cap.market == "series_moneyline":
        team1_won = bool(row["team1_won"])
        home_won = team1_won if cap.book_home_is_team1 else not team1_won
        return home_won if side == "home" else not home_won
    if cap.market == "maps_total":
        played = row.get("maps_played")
        if played is None or cap.line is None:
            return None
        over_won = played > cap.line
        return over_won if side == "home" else not over_won
    return None


def build_picks(ledger_rows: list[dict],
                captures: list[OddsCapture]) -> list[dict]:
    rows_by_id = {r["match_id"]: r for r in ledger_rows}
    grouped: dict[tuple, list[OddsCapture]] = {}
    for c in captures:
        if c.match_id and c.match_id in rows_by_id:
            grouped.setdefault(
                (c.match_id, c.market, c.line, c.source), []).append(c)

    # Headline source per (match, market, line): first in the priority list
    # that priced it. Everything else is still in the log; nothing averaged.
    headline: dict[tuple, str] = {}
    for (mid, market, line, source) in grouped:
        key = (mid, market, line)
        cur = headline.get(key)
        pr = config.ODDS_BOOK_PRIORITY
        rank = pr.index(source) if source in pr else len(pr)
        cur_rank = pr.index(cur) if cur in pr else len(pr) if cur else 99
        if cur is None or rank < cur_rank:
            headline[key] = source

    picks: list[dict] = []
    for (mid, market, line), source in sorted(headline.items()):
        caps = grouped[(mid, market, line, source)]
        row = rows_by_id[mid]
        entry, close = _entry_close(caps)
        probs = _model_side_probs(row, entry)
        if probs is None:
            continue
        p_home, p_away = probs
        ev_home = p_home * entry.price_home - 1
        ev_away = p_away * entry.price_away - 1
        side = "home" if ev_home >= ev_away else "away"
        p_model = p_home if side == "home" else p_away
        price = entry.price_home if side == "home" else entry.price_away
        dv = devig_both([entry.price_home, entry.price_away])
        i = 0 if side == "home" else 1
        clv = None
        if close is not None:
            close_price = close.price_home if side == "home" \
                else close.price_away
            clv = price / close_price - 1
        won = _grade(row, entry, side)
        if market == "series_moneyline":
            names = (row["team1_name"], row["team2_name"])
            sel_name = names[0] if (entry.book_home_is_team1 ==
                                    (side == "home")) else names[1]
        else:
            sel_name = (f"{'over' if side == 'home' else 'under'} "
                        f"{line:g} maps")
        picks.append({
            "match_id": mid, "market": market, "line": line,
            "source": source,
            "match": f"{row['team1_name']} vs {row['team2_name']}",
            "event": row.get("event", ""),
            "tier": classify_tier(row.get("event", "") or ""),
            "start_ts": row["start_ts"],
            "selection": sel_name,
            "p_model": round(p_model, 4),
            "price_entry": price,
            "implied": round(1 / price, 4),
            "shin": round(dv["shin"][i], 4),
            "multiplicative": round(dv["multiplicative"][i], 4),
            "overround": round(dv["overround"], 4),
            "ev_pct": round((p_model * price - 1) * 100, 2),
            "clv_pct": None if clv is None else round(clv * 100, 2),
            "extrapolated": not (config.EV_EXTRAPOLATION_LO <= p_model
                                 <= config.EV_EXTRAPOLATION_HI),
            "graded": won is not None,
            "won": won,
            "entry_captured_at": entry.captured_at.isoformat(),
            "close_captured": close is not None,
        })
    return picks


def _agg(picks: list[dict]) -> dict:
    graded = [p for p in picks if p["graded"]]
    core = [p for p in graded if not p["extrapolated"]]
    clv = [p["clv_pct"] for p in core if p["clv_pct"] is not None]
    out = {
        "n_covered": len(picks),
        "n_graded": len(graded),
        "n_extrapolated": sum(p["extrapolated"] for p in picks),
        "win_rate": (round(sum(p["won"] for p in graded) / len(graded), 4)
                     if graded else None),
        "avg_ev_pct": (round(sum(p["ev_pct"] for p in core) / len(core), 2)
                       if core else None),
        "avg_clv_pct": round(sum(clv) / len(clv), 2) if clv else None,
        "beat_close_rate": (round(sum(c > 0 for c in clv) / len(clv), 4)
                            if clv else None),
    }
    return out


def build_markets_report(ledger_rows: list[dict],
                         captures: list[OddsCapture],
                         now: datetime | None = None) -> dict:
    picks = build_picks(ledger_rows, captures)
    graded_n = sum(p["graded"] for p in picks)
    by_tier = {}
    for tier in sorted({p["tier"] for p in picks}):
        by_tier[tier] = _agg([p for p in picks if p["tier"] == tier])
    by_market = {}
    for market in sorted({p["market"] for p in picks}):
        by_market[market] = _agg([p for p in picks if p["market"] == market])
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "section": "LIVE",                # the frozen-ledger record; the
                                          # walk-forward BACKTEST section is
                                          # separate by design, never merged
        "gate": {"n_graded": graded_n,
                 "required": config.EV_MIN_GRADED_PICKS,
                 "ev_validated": graded_n >= config.EV_MIN_GRADED_PICKS},
        "extrapolation_band": [config.EV_EXTRAPOLATION_LO,
                               config.EV_EXTRAPOLATION_HI],
        "summary": _agg(picks),
        "by_tier": by_tier,
        "by_market": by_market,
        "picks": picks,
    }
