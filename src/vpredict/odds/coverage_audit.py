"""Markets coverage-gap audit (ASSUMPTIONS §64).

Partitions EVERY graded ledger match into exactly one bucket, so
"scoreboard graded" minus "markets covered" is fully accounted for.
Definitions are shared with the live pipeline on purpose: the same
normalize_team, the same priceable(), and the same
ODDS_LINK_MAX_START_DELTA_H tolerance the link gate uses, so the audit
cannot drift from what production actually does.

Buckets:
  1_covered                  match has at least one Markets pick
  2a_totals_only_no_dist     linked totals capture, row frozen without
                             p_maps_dist (explained: totals price only
                             from the frozen distribution)
  2b_orientation_missing     priceable moneyline, every one unoriented
                             (the n_groups_unpriced class)
  2c_unexplained             priceable, oriented moneyline and STILL no
                             pick — genuine bug candidates
  3_linked_unpriceable       only suspended/placeholder prices ever seen
  4_captured_never_linked    no linked captures, but an unlinked fixture
                             retro-matches by name (raw or alias, either
                             orientation) inside the link-gate tolerance
  5a_pre_capture_era         match predates the first capture in the log
  5b_never_listed            capture era, books never listed it

The retro-match in bucket 4 asks: "would this stored unlinked fixture
link to this graded match under TODAY'S rules?" — which is exactly the
honest definition of "odds existed, linking failed".
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .. import config
from .schema import OddsCapture, normalize_team, priceable

NOLINK_BACK_D = 14   # no book_start_ts on the capture: captured_at within
NOLINK_FWD_H = 3     # this many days before start .. hours after

ORDER = ["1_covered", "2a_totals_only_no_dist", "2b_orientation_missing",
         "2c_unexplained", "3_linked_unpriceable",
         "4_captured_never_linked", "5a_pre_capture_era",
         "5b_never_listed"]

LABELS = {
    "1_covered": "COVERED: has at least one Markets pick",
    "2a_totals_only_no_dist":
        "LINKED, NO PICK: totals-only capture, no frozen maps dist "
        "(explained)",
    "2b_orientation_missing":
        "LINKED, NO PICK: priceable moneyline, orientation missing "
        "(n_groups_unpriced class)",
    "2c_unexplained": "LINKED, NO PICK: UNEXPLAINED -- bug candidates",
    "3_linked_unpriceable":
        "LINKED, UNPRICEABLE ONLY: suspended/placeholder prices",
    "4_captured_never_linked":
        "CAPTURED, NEVER LINKED: odds existed, linking failed",
    "5a_pre_capture_era":
        "NO COVERAGE: match predates the first capture in the log",
    "5b_never_listed":
        "NO COVERAGE in capture era: books never listed it "
        "(expected gap)",
}

DETAIL = {"2c_unexplained": 5, "4_captured_never_linked": 5,
          "2b_orientation_missing": 3, "2a_totals_only_no_dist": 3,
          "3_linked_unpriceable": 3, "5b_never_listed": 3}


def _ts(v) -> datetime:
    if isinstance(v, datetime):
        d = v
    else:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _when(c: OddsCapture) -> str:
    return c.captured_at.isoformat()[:16].replace("T", " ")


def _dedupe_unlinked(captures) -> dict:
    """Earliest stored record per unlinked (source, event, market, line):
    pre-dedupe logs hold one row per 10-minute pass."""
    out: dict = {}
    for c in captures:
        if c.match_id:
            continue
        k = (c.source, c.book_event_id, c.market, c.line)
        if k not in out or c.captured_at < out[k].captured_at:
            out[k] = c
    return out


def _retro_match(c: OddsCapture, t1: str, t2: str, start: datetime,
                 aliases: dict) -> tuple[str, str] | None:
    """(method, rule) when this unlinked capture would link to the match
    under today's rules, else None."""
    bh, ba = normalize_team(c.book_home), normalize_team(c.book_away)
    pairs = [((bh, ba), "raw"),
             ((aliases.get(bh, bh), aliases.get(ba, ba)), "alias")]
    method = next((m for (p, m) in pairs
                   if p in ((t1, t2), (t2, t1))), None)
    if method is None:
        return None
    if c.book_start_ts is not None:
        ok = abs((_ts(c.book_start_ts) - start).total_seconds()) \
            <= config.ODDS_LINK_MAX_START_DELTA_H * 3600
        rule = (f"book_start within "
                f"{config.ODDS_LINK_MAX_START_DELTA_H}h")
    else:
        dt = (c.captured_at - start).total_seconds()
        ok = (-NOLINK_BACK_D * 86400) <= dt <= NOLINK_FWD_H * 3600
        rule = "captured_at plausibility (no book_start)"
    return (method, rule) if ok else None


def classify(graded_rows: list[dict], captures: list[OddsCapture],
             picks: list[dict], aliases: dict | None = None) -> dict:
    """{'buckets': {key: [info, ...]}, 'stats': {...}} — the partition
    plus the reconciliation header inputs. Pure: no IO."""
    aliases = aliases or {}
    linked: dict[str, list] = defaultdict(list)
    per_src_first: dict = {}
    for c in captures:
        if (c.source not in per_src_first
                or c.captured_at < per_src_first[c.source]):
            per_src_first[c.source] = c.captured_at
        if c.match_id:
            linked[str(c.match_id)].append(c)
    unlinked = _dedupe_unlinked(captures)
    first_cap = min(per_src_first.values()) if per_src_first else None

    pick_mids = {str(p["match_id"]) for p in picks}
    buckets: dict[str, list] = defaultdict(list)
    for row in graded_rows:
        mid = str(row["match_id"])
        start = _ts(row["start_ts"])
        info = {"mid": mid,
                "name": f"{row.get('team1_name')} vs "
                        f"{row.get('team2_name')}",
                "start": start.date().isoformat(),
                "event": (row.get("event") or "")[:44],
                "low_history": bool(row.get("low_history"))}

        if mid in pick_mids:
            buckets["1_covered"].append(info)
            continue

        lc = linked.get(mid, [])
        if lc:
            pr = [c for c in lc if priceable(c)]
            info["n_caps"] = len(lc)
            info["sources"] = sorted({c.source for c in lc})
            info["kinds"] = dict(Counter(c.capture_kind for c in lc))
            if not pr:
                buckets["3_linked_unpriceable"].append(info)
                continue
            ml = [c for c in pr if c.market == "series_moneyline"]
            if not ml:
                if row.get("p_maps_dist"):
                    info["why"] = ("totals-only capture, row HAS "
                                   "p_maps_dist -> should have priced")
                    buckets["2c_unexplained"].append(info)
                else:
                    buckets["2a_totals_only_no_dist"].append(info)
                continue
            oriented = [c for c in ml
                        if c.book_home_is_team1 is not None]
            if not oriented:
                buckets["2b_orientation_missing"].append(info)
                continue
            info["priceable_ml"] = len(oriented)
            info["example_price"] = (oriented[0].price_home,
                                     oriented[0].price_away)
            info["first_cap"] = _when(oriented[0])
            buckets["2c_unexplained"].append(info)
            continue

        t1 = normalize_team(row.get("team1_name"))
        t2 = normalize_team(row.get("team2_name"))
        hit = None
        for c in unlinked.values():
            got = _retro_match(c, t1, t2, start, aliases)
            if got:
                hit = (c, *got)
                break
        if hit:
            c, method, rule = hit
            info.update({
                "book": f"{c.book_home} vs {c.book_away}",
                "source": c.source, "captured": _when(c),
                "would_link_via": f"{method}, {rule}",
                "priceable": priceable(c)})
            buckets["4_captured_never_linked"].append(info)
            continue

        if first_cap and start < first_cap:
            buckets["5a_pre_capture_era"].append(info)
        else:
            buckets["5b_never_listed"].append(info)

    caps_ts = [c.captured_at for c in captures]
    stats = {
        "n_graded": len(graded_rows),
        "log_first": min(caps_ts).isoformat() if caps_ts else None,
        "log_last": max(caps_ts).isoformat() if caps_ts else None,
        "n_low_history": sum(1 for r in graded_rows
                             if r.get("low_history")),
        "n_captures": len(captures),
        "n_linked_matches": len(linked),
        "n_unlinked_fixtures": len(unlinked),
        "first_capture_per_source": {
            s: t.isoformat() for s, t in sorted(per_src_first.items())},
        "pick_mids": pick_mids,
    }
    return {"buckets": dict(buckets), "stats": stats}


def render(result: dict, picks: list[dict], markets_meta: dict,
           pending_n: int | None = None) -> str:
    """The report string, identical in shape to the first production run
    (2026-08-08) so results stay comparable over time."""
    buckets, st = result["buckets"], result["stats"]
    builder = (markets_meta.get("builder")
               or "UNSTAMPED (pre-0081 build or foreign write)")
    lines = ["=" * 70, "RECONCILIATION",
             f"  markets.json generated_at: "
             f"{markets_meta.get('generated_at')}  builder: {builder}",
             f"  ledger: {st['n_graded']} graded rows"
             + (f", {pending_n} pending" if pending_n is not None
                else ""),
             f"          ({st['n_low_history']} of the graded rows are "
             "low_history: listed, not scored)"]
    bym = Counter(p["market"] for p in picks)
    graded_mids = {i["mid"] for b in buckets.values() for i in b}
    pick_mids = st["pick_mids"]
    lines += [
        f"  markets picks: {len(picks)} total ({dict(bym)}); distinct "
        f"matches {len(pick_mids)}",
        f"    covering {len(pick_mids & graded_mids)} graded matches "
        f"and {len(pick_mids - graded_mids)} pending/other",
        f"  markets skipped counters: {markets_meta.get('skipped')}",
        f"  capture log: {st['n_captures']} rows; linked matches "
        f"{st['n_linked_matches']}; unlinked fixtures (deduped) "
        f"{st['n_unlinked_fixtures']}",
        f"  capture log span: {st.get('log_first')} .. "
        f"{st.get('log_last')}"]
    for s, t in st["first_capture_per_source"].items():
        lines.append(f"    first {s} capture: {t}")
    lines += ["=" * 70,
              f"PARTITION OF THE {st['n_graded']} GRADED MATCHES"]
    total = 0
    for key in ORDER:
        rows = buckets.get(key, [])
        total += len(rows)
        lines.append(f"\n[{len(rows):3d}] {LABELS[key]}")
        for info in rows[:DETAIL.get(key, 0)]:
            extra = {k: v for k, v in info.items()
                     if k not in ("mid", "name", "start", "event")}
            lines.append(f"      {info['start']}  {info['name']}  "
                         f"({info['event']})")
            if extra:
                lines.append(f"        {extra}")
        if len(rows) > DETAIL.get(key, 0) > 0:
            lines.append(f"      ... and {len(rows) - DETAIL[key]} more")
    ok = total == st["n_graded"]
    bug = (len(buckets.get("2c_unexplained", []))
           + len(buckets.get("4_captured_never_linked", [])))
    exp = sum(len(buckets.get(k, []))
              for k in ("5a_pre_capture_era", "5b_never_listed",
                        "3_linked_unpriceable", "2a_totals_only_no_dist",
                        "2b_orientation_missing"))
    lines += ["\n" + "=" * 70,
              f"SUM CHECK: {total} classified == {st['n_graded']} "
              f"graded: {'OK' if ok else 'MISMATCH -- report this'}",
              f"HEADLINE: covered {len(buckets.get('1_covered', []))}; "
              f"expected gap {exp}; had-odds-but-missing (investigate) "
              f"{bug}"]
    return "\n".join(lines)
