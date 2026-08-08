"""Coverage-gap audit (ASSUMPTIONS §64): the partition of graded matches
is exhaustive and mutually exclusive, and every bucket's rule is pinned,
including both retro-link variants (raw names and alias with flipped
book orientation) and the pre-era/never-listed split."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from vpredict.odds.coverage_audit import ORDER, classify, render
from vpredict.odds.schema import OddsCapture

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def _row(mid, n1, n2, days_ago, dist=None, low=0):
    st = NOW - timedelta(days=days_ago)
    return {"match_id": mid, "start_ts": st.isoformat(),
            "team1_name": n1, "team2_name": n2,
            "event": "VCL Test League", "low_history": low,
            "p_maps_dist": json.dumps(dist) if dist else None}


def _cap(mid, home, away, days_ago, ph=1.8, pa=2.0,
         market="series_moneyline", line=None, orient=True, bs=True):
    t = NOW - timedelta(days=days_ago)
    return OddsCapture(
        captured_at=t, source="cloudbet", capture_kind="freeze",
        market=market, line=line,
        book_event_id=f"e-{home}-{away}-{market}",
        book_home=home, book_away=away,
        book_start_ts=t if bs else None,
        price_home=ph, price_away=pa, match_id=mid,
        book_home_is_team1=(True if orient and mid else None),
        link_method="exact" if mid else None)


ROWS = [
    _row("A", "Alpha", "Beta", 2),           # covered
    _row("B", "Gamma", "Delta", 3),          # 2c unexplained
    _row("C", "Eps", "Zeta", 4),             # 2a totals-only, no dist
    _row("C2", "Om", "Psi", 4,
         dist={"2": 0.5, "3": 0.5}),         # 2c: totals-only WITH dist
    _row("D", "Eta", "Theta", 5),            # 3 unpriceable only
    _row("E", "Iota FC", "Kappa", 6),        # 4 raw retro-match
    _row("E2", "Lambda", "Mu Esports", 6),   # 4 alias retro-match, flipped
    _row("F", "Nu", "Xi", 5),                # 5b never listed
    _row("G", "Old One", "Old Two", 40),     # 5a pre-era
    _row("H", "Pi", "Rho", 3),               # 2b orientation missing
]

CAPS = [
    _cap("A", "Alpha", "Beta", 2.1),
    _cap("B", "Gamma", "Delta", 3.1),
    _cap("C", "Eps", "Zeta", 4.1, market="maps_total", line=2.5),
    _cap("C2", "Om", "Psi", 4.1, market="maps_total", line=2.5),
    _cap("D", "Eta", "Theta", 5.1, ph=0.0, pa=0.0),
    _cap(None, "Iota FC", "Kappa", 6.02),
    _cap(None, "MU", "Lambda", 6.02),        # flipped + alias-able
    _cap("H", "Pi", "Rho", 3.1, orient=False),
]

PICKS = [{"match_id": "A", "market": "series_moneyline", "line": None}]
ALIASES = {"mu": "muesports"}


def _got():
    return classify(ROWS, CAPS, PICKS, ALIASES)


def test_partition_is_exhaustive_and_mutually_exclusive():
    b = _got()["buckets"]
    ids = [i["mid"] for k in ORDER for i in b.get(k, [])]
    assert sorted(ids) == sorted(r["match_id"] for r in ROWS)
    assert len(ids) == len(set(ids))


def test_every_bucket_gets_exactly_its_scenario():
    b = _got()["buckets"]
    got = {k: sorted(i["mid"] for i in v) for k, v in b.items()}
    assert got == {
        "1_covered": ["A"],
        "2a_totals_only_no_dist": ["C"],
        "2b_orientation_missing": ["H"],
        "2c_unexplained": ["B", "C2"],
        "3_linked_unpriceable": ["D"],
        "4_captured_never_linked": ["E", "E2"],
        "5a_pre_capture_era": ["G"],
        "5b_never_listed": ["F"],
    }


def test_retro_match_records_method_and_rule():
    by = {i["mid"]: i
          for i in _got()["buckets"]["4_captured_never_linked"]}
    assert by["E"]["would_link_via"].startswith("raw,")
    assert by["E2"]["would_link_via"].startswith("alias,")
    assert by["E2"]["book"] == "MU vs Lambda"      # flipped orientation


def test_time_gate_blocks_a_name_coincidence_days_away():
    rows = [_row("Z", "Same Name", "Other Name", 2)]
    caps = [_cap(None, "Same Name", "Other Name", 9.0)]   # 7 days off
    b = classify(rows, caps, [], {})["buckets"]
    assert [i["mid"] for i in b.get("5b_never_listed", [])] == ["Z"]
    assert "4_captured_never_linked" not in b


def test_totals_with_frozen_dist_is_flagged_not_explained():
    info = next(i for i in _got()["buckets"]["2c_unexplained"]
                if i["mid"] == "C2")
    assert "should have priced" in info["why"]


def test_render_sum_check_reads_ok():
    out = render(_got(), PICKS, {"generated_at": NOW.isoformat(),
                                 "skipped": {}}, pending_n=0)
    assert "SUM CHECK: 10 classified == 10 graded: OK" in out
    assert "had-odds-but-missing (investigate) 4" in out
