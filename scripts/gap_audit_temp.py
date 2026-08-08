#!/usr/bin/env python3
"""Markets coverage-gap audit (read-only, stdlib only).

Classifies EVERY graded ledger match into exactly one bucket, so
"scoreboard graded" minus "markets covered" is fully accounted for:

  1 COVERED                match has at least one Markets pick
  2 LINKED, NO PICK        captures linked to it, but no pick emitted
      2a totals-only, row has no frozen maps distribution (explained:
         totals price only from p_maps_dist, ASSUMPTIONS S14 area)
      2b priceable moneyline but orientation missing on every one
         (the n_groups_unpriced class)
      2c UNEXPLAINED       priceable, oriented moneyline exists and
         still no pick -- genuine bug candidates, full detail printed
  3 LINKED, UNPRICEABLE    only suspended/placeholder prices ever seen
  4 CAPTURED, NEVER LINKED no linked captures, but an UNLINKED fixture
      retro-matches this match by name (raw or alias) within the link
      gate's time tolerance -- odds existed, linking failed
  5 NO COVERAGE            nothing captured that maps to this match
      5a match started before the first capture in the log (pre-era)
      5b capture era, books never listed it (the genuine expected gap)

Run in the Render Shell:
    python3 /tmp/gap_audit.py            # reads /data
    python3 /tmp/gap_audit.py --data X   # any other data root
Writes nothing. Prints a reconciliation header, the partition with a
sum check, and concrete examples for the interesting classes.
"""
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

DATA = "/data"
if "--data" in sys.argv:
    DATA = sys.argv[sys.argv.index("--data") + 1]

LINK_GATE_H = 6           # same tolerance as ODDS_LINK_MAX_START_DELTA_H
NOLINK_BACK_D = 14        # no book_start_ts: captured_at within this many
NOLINK_FWD_H = 3          # days before start .. this many hours after

_STRIP = re.compile(r"[^a-z0-9]+")


def norm(s):
    return _STRIP.sub("", (s or "").casefold())


def ts(v):
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def priceable(c):
    try:
        h, a = float(c.get("price_home")), float(c.get("price_away"))
    except (TypeError, ValueError):
        return False
    return math.isfinite(h) and math.isfinite(a) and h > 1.0 and a > 1.0


def when(c):
    return str(c.get("captured_at", ""))[:16].replace("T", " ")


def main():
    # ---- inputs -----------------------------------------------------
    con = sqlite3.connect(f"{DATA}/serving/ledger.sqlite")
    con.row_factory = sqlite3.Row
    graded = [dict(r) for r in con.execute(
        "SELECT * FROM predictions WHERE graded=1")]
    pending_n = con.execute(
        "SELECT COUNT(*) FROM predictions WHERE graded=0").fetchone()[0]

    caps = []
    with open(f"{DATA}/odds/odds.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                caps.append(json.loads(line))

    mk = json.load(open(f"{DATA}/processed/markets.json", encoding="utf-8"))
    picks = mk.get("picks", [])

    aliases = {}
    try:
        raw = json.load(open(f"{DATA}/odds/aliases.json", encoding="utf-8"))
        aliases = {norm(k): norm(v) for k, v in raw.items()}
    except (FileNotFoundError, ValueError):
        pass

    # ---- reconciliation header -------------------------------------
    linked = defaultdict(list)
    unlinked = {}
    per_src_first = {}
    for c in caps:
        src = c.get("source", "?")
        t = ts(c["captured_at"])
        if src not in per_src_first or t < per_src_first[src]:
            per_src_first[src] = t
        if c.get("match_id"):
            linked[str(c["match_id"])].append(c)
        else:
            k = (src, c.get("book_event_id"), c.get("market"),
                 c.get("line"))
            if k not in unlinked or t < ts(unlinked[k]["captured_at"]):
                unlinked[k] = c
    first_cap = min(per_src_first.values()) if per_src_first else None

    pick_mids = {str(p["match_id"]) for p in picks}
    graded_mids = {str(r["match_id"]) for r in graded}
    print("=" * 70)
    print("RECONCILIATION")
    print(f"  markets.json generated_at: {mk.get('generated_at')}")
    print(f"  ledger: {len(graded)} graded rows, {pending_n} pending")
    lowh = sum(1 for r in graded if r.get("low_history"))
    print(f"          ({lowh} of the graded rows are low_history: "
          "listed, not scored)")
    bym = Counter(p["market"] for p in picks)
    print(f"  markets picks: {len(picks)} total "
          f"({dict(bym)}); distinct matches {len(pick_mids)}")
    print(f"    covering {len(pick_mids & graded_mids)} graded matches "
          f"and {len(pick_mids - graded_mids)} pending/other")
    print(f"  markets skipped counters: {mk.get('skipped')}")
    print(f"  capture log: {len(caps)} rows; linked matches "
          f"{len(linked)}; unlinked fixtures (deduped) {len(unlinked)}")
    for s, t in sorted(per_src_first.items()):
        print(f"    first {s} capture: {t.isoformat()}")

    # ---- classification --------------------------------------------
    buckets = defaultdict(list)
    for row in graded:
        mid = str(row["match_id"])
        name = f"{row.get('team1_name')} vs {row.get('team2_name')}"
        start = ts(row["start_ts"])
        info = {"mid": mid, "name": name,
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
            info["sources"] = sorted({c.get("source") for c in lc})
            info["kinds"] = dict(Counter(
                c.get("capture_kind") for c in lc))
            if not pr:
                buckets["3_linked_unpriceable"].append(info)
                continue
            ml = [c for c in pr
                  if c.get("market") == "series_moneyline"]
            if not ml:
                if row.get("p_maps_dist"):
                    info["why"] = ("totals-only capture, row HAS "
                                   "p_maps_dist -> should have priced")
                    buckets["2c_unexplained"].append(info)
                else:
                    buckets["2a_totals_only_no_dist"].append(info)
                continue
            oriented = [c for c in ml
                        if c.get("book_home_is_team1") is not None]
            if not oriented:
                buckets["2b_orientation_missing"].append(info)
                continue
            info["priceable_ml"] = len(oriented)
            info["example_price"] = (oriented[0].get("price_home"),
                                     oriented[0].get("price_away"))
            info["first_cap"] = when(oriented[0])
            buckets["2c_unexplained"].append(info)
            continue

        # no linked captures: retro-match the unlinked pool
        t1, t2 = norm(row.get("team1_name")), norm(row.get("team2_name"))
        hit = None
        for c in unlinked.values():
            bh, ba = norm(c.get("book_home")), norm(c.get("book_away"))
            pairs = [((bh, ba), "raw"),
                     ((aliases.get(bh, bh), aliases.get(ba, ba)),
                      "alias")]
            method = next((m for (p, m) in pairs
                           if p in ((t1, t2), (t2, t1))), None)
            if method is None:
                continue
            bs = c.get("book_start_ts")
            if bs:
                ok = abs((ts(bs) - start).total_seconds()) \
                    <= LINK_GATE_H * 3600
                rule = f"book_start within {LINK_GATE_H}h"
            else:
                dt = (ts(c["captured_at"]) - start).total_seconds()
                ok = (-NOLINK_BACK_D * 86400) <= dt <= NOLINK_FWD_H * 3600
                rule = "captured_at plausibility (no book_start)"
            if ok:
                hit = (c, method, rule)
                break
        if hit:
            c, method, rule = hit
            info.update({
                "book": f"{c.get('book_home')} vs {c.get('book_away')}",
                "source": c.get("source"), "captured": when(c),
                "would_link_via": f"{method}, {rule}",
                "priceable": priceable(c)})
            buckets["4_captured_never_linked"].append(info)
            continue

        if first_cap and start < first_cap:
            buckets["5a_pre_capture_era"].append(info)
        else:
            buckets["5b_never_listed"].append(info)

    # ---- report -----------------------------------------------------
    order = ["1_covered", "2a_totals_only_no_dist",
             "2b_orientation_missing", "2c_unexplained",
             "3_linked_unpriceable", "4_captured_never_linked",
             "5a_pre_capture_era", "5b_never_listed"]
    labels = {
        "1_covered": "COVERED: has at least one Markets pick",
        "2a_totals_only_no_dist":
            "LINKED, NO PICK: totals-only capture, no frozen maps dist "
            "(explained)",
        "2b_orientation_missing":
            "LINKED, NO PICK: priceable moneyline, orientation missing "
            "(n_groups_unpriced class)",
        "2c_unexplained":
            "LINKED, NO PICK: UNEXPLAINED -- bug candidates",
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
    detail = {"2c_unexplained": 5, "4_captured_never_linked": 5,
              "2b_orientation_missing": 3, "2a_totals_only_no_dist": 3,
              "3_linked_unpriceable": 3, "5b_never_listed": 3}
    print("=" * 70)
    print(f"PARTITION OF THE {len(graded)} GRADED MATCHES")
    total = 0
    for key in order:
        rows = buckets.get(key, [])
        total += len(rows)
        print(f"\n[{len(rows):3d}] {labels[key]}")
        for info in rows[:detail.get(key, 0)]:
            extra = {k: v for k, v in info.items()
                     if k not in ("mid", "name", "start", "event")}
            print(f"      {info['start']}  {info['name']}  "
                  f"({info['event']})")
            if extra:
                print(f"        {extra}")
        if len(rows) > detail.get(key, 0) > 0:
            print(f"      ... and {len(rows) - detail[key]} more")
    print("\n" + "=" * 70)
    ok = total == len(graded)
    print(f"SUM CHECK: {total} classified == {len(graded)} graded: "
          f"{'OK' if ok else 'MISMATCH -- report this'}")
    bug = (len(buckets['2c_unexplained'])
           + len(buckets['4_captured_never_linked']))
    exp = (len(buckets['5a_pre_capture_era'])
           + len(buckets['5b_never_listed'])
           + len(buckets['3_linked_unpriceable'])
           + len(buckets['2a_totals_only_no_dist'])
           + len(buckets['2b_orientation_missing']))
    print(f"HEADLINE: covered {len(buckets['1_covered'])}; expected gap "
          f"{exp}; had-odds-but-missing (investigate) {bug}")


if __name__ == "__main__":
    main()
