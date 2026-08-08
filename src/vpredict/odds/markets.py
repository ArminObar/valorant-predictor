"""Markets & EV analysis — joins the frozen ledger with the odds log.

Every number here derives from two append-only records: the ledger row
frozen >=5 min before start (p_model, p_maps_dist) and the odds captures
(raw decimal prices at freeze and close). Nothing is recomputed with a
newer model, so the model-vs-market comparison can never be revised
favourably after the fact.

Definitions, recorded in ASSUMPTIONS §15:
  pick        per (match, market, line): the side with the higher EV, each
              side priced at its best ENTRY (freeze) price across books
              (§43). Sides are CANONICAL — team1/OVER vs team2/UNDER —
              never the books' own listing order (LOG entry 55). A pick
              can carry negative EV; the display labels the pick-vs-model
              relationship instead of hiding the row (owner call, §56).
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
import logging
import math
from datetime import datetime, timezone

from .. import config
from ..evaluation.tiers import classify_tier
from .devig import devig_both
from .schema import OddsCapture, priceable as schema_priceable

log = logging.getLogger("vpredict.markets")


def _priceable(c: OddsCapture) -> bool:
    """Single definition lives in schema.priceable so the capture loop and
    this build can never disagree about what counts as a price (LOG
    entries 47 and 59)."""
    return schema_priceable(c)


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
    """(p_side0, p_side1) in CANONICAL orientation — side 0 is team1 for
    moneylines and OVER for totals, whatever the book's listing order.
    None when the frozen record can't price the market (a totals capture
    for a row frozen before p_maps_dist existed, or a moneyline capture
    whose orientation was never linked)."""
    if cap.market == "series_moneyline":
        if cap.book_home_is_team1 is None:
            return None
        p1 = float(row["p_model"])
        return (p1, 1 - p1)
    if cap.market == "maps_total":
        raw = row.get("p_maps_dist")
        if not raw or cap.line is None:
            return None
        dist = {int(k): float(v) for k, v in json.loads(raw).items()}
        p_over = sum(v for k, v in dist.items() if k > cap.line)
        return p_over, 1 - p_over          # home=OVER, away=UNDER convention
    return None


def _grade(row: dict, market: str, line: float | None, s: int) -> bool | None:
    """Did CANONICAL side s (0 = team1 / OVER, 1 = team2 / UNDER) win?
    None while ungraded / ungradeable."""
    if not row.get("graded"):
        return None
    if market == "series_moneyline":
        team1_won = bool(row["team1_won"])
        return team1_won if s == 0 else not team1_won
    if market == "maps_total":
        played = row.get("maps_played")
        if played is None or line is None:
            return None
        over_won = played > line
        return over_won if s == 0 else not over_won
    return None


def build_picks(ledger_rows: list[dict],
                captures: list[OddsCapture],
                ) -> tuple[list[dict], dict]:
    """Returns (picks, skipped). skipped["n_unpriceable"] counts capture
    records set aside by _priceable (placeholder, negative, or non-finite
    prices; only records that would have joined the build are counted).
    skipped["n_group_errors"] counts pick groups abandoned by the
    last-resort isolation below. The strict guard stays in devig.py
    (LOG entries 46 and 47); this caller skips and counts, loudly, so no
    single record or group can take down the whole build."""
    rows_by_id = {r["match_id"]: r for r in ledger_rows}
    skipped = {"n_unpriceable": 0, "n_group_errors": 0,
               "n_groups_unpriced": 0}
    usable: list[OddsCapture] = []
    for c in captures:
        if _priceable(c):
            usable.append(c)
        elif c.match_id and c.match_id in rows_by_id:
            skipped["n_unpriceable"] += 1     # would have joined the build
    grouped: dict[tuple, list[OddsCapture]] = {}
    for c in usable:
        if c.match_id and c.match_id in rows_by_id:
            grouped.setdefault(
                (c.match_id, c.market, c.line, c.source), []).append(c)

    # Best line per (match, market, line): the pick's side is chosen on the
    # best available ENTRY price for that side across every source with a
    # freeze capture, and the entry book is whichever source offered it
    # (ties break by ODDS_BOOK_PRIORITY, then name). Pre-registered rules
    # (ASSUMPTIONS §43): CLV grades against the entry book's own close ONLY;
    # the validation gate still counts one pick per (match, market, line)
    # whatever the book count; best-of-books EV is upward biased and ships
    # with a consensus de-vig beside it. All prices stay in the log;
    # nothing is averaged into EV.
    by_key: dict[tuple, dict[str, list[OddsCapture]]] = {}
    for (mid, market, line, source), caps in grouped.items():
        by_key.setdefault((mid, market, line), {})[source] = caps

    def _rank(source: str) -> tuple:
        pr = config.ODDS_BOOK_PRIORITY
        return (pr.index(source) if source in pr else len(pr), source)

    picks: list[dict] = []

    def _group_order(item):
        (gmid, gmarket, gline), _ = item
        return (gmid, gmarket, gline is not None,
                0.0 if gline is None else gline)

    for (mid, market, line), sources in sorted(by_key.items(),
                                               key=_group_order):
        row = rows_by_id[mid]
        try:
            entries = {src: _entry_close(caps) for src, caps in sources.items()}
            # Per-source model side-probs (book orientation can differ by book).
            priced = {}
            for src, (entry, close) in entries.items():
                probs = _model_side_probs(row, entry)
                if probs is not None:
                    priced[src] = (entry, close, probs)
            if not priced:
                # Every source's entry failed _model_side_probs: an
                # unlinked-orientation moneyline or a totals capture with
                # no frozen maps distribution. Counted so a match with
                # real captured odds can never vanish from Markets
                # silently (LOG entry 61).
                skipped["n_groups_unpriced"] += 1
                continue

            def _bidx(cap2: OddsCapture, cs: int) -> int | None:
                """Index into (price_home, price_away) for CANONICAL side cs
                (0 = team1 / OVER, 1 = team2 / UNDER). Totals are canonical
                by capture convention (home = OVER at every book); moneyline
                maps through the capture's own linked orientation. None when
                a moneyline capture's orientation is unlinked."""
                if cap2.market != "series_moneyline":
                    return cs
                if cap2.book_home_is_team1 is None:
                    return None
                return cs if cap2.book_home_is_team1 else 1 - cs

            def _price_of(cap2: OddsCapture, cs: int) -> float | None:
                j = _bidx(cap2, cs)
                if j is None:
                    return None
                return cap2.price_home if j == 0 else cap2.price_away

            # Best entry price per CANONICAL side across books, EV per side
            # at its best price. Comparing by the books' own home/away
            # labels scrambled sides whenever two books listed the same
            # match in opposite order: one team could leave the menu
            # entirely and the consensus mixed sides (LOG entry 55).
            def best_for(cs: int):
                best = None
                for src in sorted(priced, key=_rank):
                    entry, close, probs = priced[src]
                    price = _price_of(entry, cs)
                    if price is None:
                        continue
                    if best is None or price > best[0]:
                        best = (price, probs[cs], src, entry, close)
                return best
            b0, b1 = best_for(0), best_for(1)
            ev0 = b0[1] * b0[0] - 1
            ev1 = b1[1] * b1[0] - 1
            s = 0 if ev0 >= ev1 else 1
            price, p_model, source, entry, close = b0 if s == 0 else b1
            # Consensus fair probability for the chosen side: median Shin
            # de-vig across every book's ENTRY capture (n=2 today: the
            # midpoint), each book indexed through its OWN orientation so
            # every contribution is the same team's number.
            cons = []
            for src, (e2, _c2, _p2) in priced.items():
                j2 = _bidx(e2, s)
                if j2 is None:
                    continue
                dv2 = devig_both([e2.price_home, e2.price_away])
                cons.append(dv2["shin"][j2])
            cons.sort()
            n = len(cons)
            shin_consensus = (cons[n // 2] if n % 2
                              else (cons[n // 2 - 1] + cons[n // 2]) / 2)
            dv = devig_both([entry.price_home, entry.price_away])
            i = _bidx(entry, s)
            clv = None
            if close is not None and entry.capture_kind == "freeze":
                # The close capture maps through its OWN orientation: a book
                # that flips its listing between entry and close still
                # grades the same team's price. When the group never got a
                # true freeze, entry IS the close and price/close_price is
                # identically 1: that is a fabricated perfect CLV, not a
                # measurement, so it stays None (LOG entry 59).
                close_price = _price_of(close, s)
                if close_price is not None:
                    clv = price / close_price - 1
            won = _grade(row, market, line, s)
            if market == "series_moneyline":
                sel_name = (row["team1_name"] if s == 0
                            else row["team2_name"])
            else:
                sel_name = (f"{'over' if s == 0 else 'under'} "
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
                "shin_consensus": round(shin_consensus, 4),
                "n_books": len(priced),
                "multiplicative": round(dv["multiplicative"][i], 4),
                "overround": round(dv["overround"], 4),
                "ev_pct": round((p_model * price - 1) * 100, 2),
                "clv_pct": None if clv is None else round(clv * 100, 2),
                "extrapolated": not (config.EV_EXTRAPOLATION_LO <= p_model
                                     <= config.EV_EXTRAPOLATION_HI),
                "graded": won is not None,
                "won": won,
                "entry_captured_at": entry.captured_at.isoformat(),
                "entry_kind": entry.capture_kind,
                "close_captured": close is not None,
            })
        except Exception:
            skipped["n_group_errors"] += 1
            log.exception("pick group (%s, %s, %s) failed; skipped so the "
                          "rest of the build survives", mid, market, line)
    return picks, skipped


def _ev_excluded(p: dict) -> str | None:
    """Why this pick's EV/CLV stay out of the aggregates, or None.
    Extrapolation was §14's rule; totals joined it by owner direction
    (§20): the frozen maps distribution's independence assumption is
    measured ~7 points off on P(2-0), so its EV is a known-biased number
    and does not ship as if it were clean. The pick itself stays visible —
    frozen data is the record — with the reason attached."""
    if p["extrapolated"]:
        return "extrapolation"
    if config.EV_EXCLUDE_TOTALS and p["market"] == "maps_total":
        return "totals_independence_bias"
    return None


def _agg(picks: list[dict]) -> dict:
    graded = [p for p in picks if p["graded"]]
    core = [p for p in graded if _ev_excluded(p) is None]
    clv = [p["clv_pct"] for p in core if p["clv_pct"] is not None]
    out = {
        "n_covered": len(picks),
        "n_graded": len(graded),
        "n_extrapolated": sum(p["extrapolated"] for p in picks),
        "n_ev_excluded": sum(_ev_excluded(p) is not None for p in picks),
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
                         now: datetime | None = None,
                         section: str = "LIVE") -> dict:
    picks, skipped = build_picks(ledger_rows, captures)
    for p in picks:
        p["ev_excluded"] = _ev_excluded(p)
    # The validation gate counts only picks whose EV methodology is the one
    # being validated: a known-biased totals EV cannot help validate EV.
    graded_n = sum(p["graded"] and _ev_excluded(p) is None for p in picks)
    by_tier = {}
    for tier in sorted({p["tier"] for p in picks}):
        by_tier[tier] = _agg([p for p in picks if p["tier"] == tier])
    by_market = {}
    for market in sorted({p["market"] for p in picks}):
        by_market[market] = _agg([p for p in picks if p["market"] == market])
    gate = {"n_graded": graded_n,
            "required": config.EV_MIN_GRADED_PICKS,
            "ev_validated": graded_n >= config.EV_MIN_GRADED_PICKS}
    from .unit_tracker import compute_unit_tracker
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "section": section,               # "LIVE" (frozen ledger) or
                                          # "BACKTEST" (simulated) — the two
                                          # are separate by design, never
                                          # merged into one number
        "skipped": skipped,
        "gate": gate,
        "unit_tracker": compute_unit_tracker(picks, gate),
        "extrapolation_band": [config.EV_EXTRAPOLATION_LO,
                               config.EV_EXTRAPOLATION_HI],
        "summary": _agg(picks),
        "by_tier": by_tier,
        "by_market": by_market,
        "picks": picks,
    }
