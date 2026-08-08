"""Unit tracker (ASSUMPTIONS §59): quarter Kelly, imaginary units,
clamped so no outlier EV can dominate, provisional with the EV gate."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from vpredict import config
from vpredict.odds.markets import build_markets_report
from vpredict.odds.schema import OddsCapture
from vpredict.odds.unit_tracker import compute_unit_tracker, stake_units

GATE_OPEN = {"n_graded": 3, "required": 100, "ev_validated": False}
GATE_PASSED = {"n_graded": 120, "required": 100, "ev_validated": True}


def _pick(ev_pct=8.0, price=2.00, won=True, start="2026-08-09T12:00:00Z",
          market="series_moneyline", graded=True, ev_excluded=None,
          mid="m1"):
    return {"match_id": mid, "match": "Alpha vs Beta", "selection": "Alpha",
            "start_ts": start, "market": market, "price_entry": price,
            "ev_pct": ev_pct, "graded": graded, "won": won,
            "ev_excluded": ev_excluded}


# ------------------------------------------------------------ stake clamps

def test_stake_is_quarter_kelly_on_fixed_notional():
    # f* = EV/(d-1); quarter of 100u notional: 25 * 0.08 / 1.0 = 2.0u.
    assert stake_units(0.08, 2.00) == pytest.approx(2.0)


def test_ev_clip_bounds_outlier_influence():
    # A claimed +30% EV sizes as +10%: 25 * 0.10 / 1.5 = 1.6667u — the
    # stake an outlier gets is the same one a 10% pick gets.
    assert stake_units(0.30, 2.50) == pytest.approx(25 * 0.10 / 1.5,
                                                    abs=1e-4)


def test_stake_cap_is_a_hard_ceiling():
    # Short price: unclamped quarter Kelly would stake 4.5u; cap holds 3.0.
    assert stake_units(0.09, 1.50) == pytest.approx(3.0)


def test_no_edge_no_stake():
    assert stake_units(0.0, 2.0) == 0.0
    assert stake_units(-0.05, 2.0) == 0.0
    assert stake_units(0.10, 1.0) == 0.0


# ------------------------------------------------- eligibility + settlement

def test_settlement_and_flat_companion_line():
    picks = [_pick(ev_pct=8.0, price=2.00, won=True, mid="w"),
             _pick(ev_pct=8.0, price=2.00, won=False, mid="l")]
    t = compute_unit_tracker(picks, GATE_OPEN)
    assert t["n_staked"] == 2 and t["n_wins"] == 1
    assert t["units_staked"] == pytest.approx(4.0)
    # win +2.0, loss -2.0 -> net 0; flat line: +1.0 - 1.0 = 0.
    assert t["units_pnl"] == pytest.approx(0.0)
    assert t["flat_pnl_units"] == pytest.approx(0.0)
    assert t["roi_pct"] == pytest.approx(0.0)


def test_eligibility_mirrors_the_ev_gate():
    picks = [
        _pick(mid="ok"),
        _pick(mid="neg", ev_pct=-3.0),                 # no positive edge
        _pick(mid="tot", market="maps_total",
              ev_excluded="totals_independence_bias"),  # gate-excluded
        _pick(mid="ext", ev_excluded="extrapolation"),  # gate-excluded
        _pick(mid="pend", graded=False, won=None),      # ungraded
        _pick(mid="old", start="2026-08-01T00:00:00Z"),  # pre-boundary
    ]
    t = compute_unit_tracker(picks, GATE_OPEN)
    assert [r["match_id"] for r in t["picks"]] == ["ok"]


def test_boundary_is_inclusive_at_start_ts():
    t = compute_unit_tracker([_pick(start=config.UNIT_TRACKER_START_TS)],
                             GATE_OPEN)
    assert t["n_staked"] == 1


def test_provisional_tracks_the_ev_gate_not_its_own_n():
    picks = [_pick()]
    assert compute_unit_tracker(picks, GATE_OPEN)["provisional"] is True
    assert compute_unit_tracker(picks, GATE_PASSED)["provisional"] is False


def test_empty_input_is_well_formed():
    t = compute_unit_tracker([], GATE_OPEN)
    assert t["n_staked"] == 0 and t["units_pnl"] == 0.0
    assert t["roi_pct"] is None and t["provisional"] is True


# ------------------------------------------------------------ report wiring

def _row_aug(p_model=0.62):
    return {"match_id": "m9", "team1_name": "Alpha", "team2_name": "Beta",
            "event": "VCT 2026: Americas", "best_of": 3,
            "start_ts": "2026-08-09T08:00:00+00:00", "p_model": p_model,
            "graded": 1, "team1_won": 1, "maps_played": 2,
            "p_maps_dist": None}


def test_report_ships_tracker_and_boundary_filters_prefix_picks(monkeypatch):
    caps = [OddsCapture(
        captured_at=datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc),
        source="cloudbet", capture_kind="freeze", book_event_id="1",
        book_home="Alpha", book_away="Beta", price_home=1.80,
        price_away=2.02, match_id="m9", book_home_is_team1=True)]
    rep = build_markets_report([_row_aug()], caps)
    t = rep["unit_tracker"]
    # p=0.62 at 1.80: EV 11.6% clips to 10% for sizing; 25*0.10/0.80 =
    # 3.125u capped at 3.0u; Alpha won -> +3.0 * 0.80 = +2.4u.
    assert t["n_staked"] == 1
    assert t["picks"][0]["stake_units"] == pytest.approx(3.0)
    assert t["units_pnl"] == pytest.approx(2.4)
    assert t["provisional"] is True
    # Move the boundary past the match: the same pick no longer counts.
    monkeypatch.setattr(config, "UNIT_TRACKER_START_TS",
                        "2026-08-10T00:00:00+00:00")
    rep2 = build_markets_report([_row_aug()], caps)
    assert rep2["unit_tracker"]["n_staked"] == 0
