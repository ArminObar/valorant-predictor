"""Markets & EV tests (spec item 5).

Pins: the exact maps-played distribution and its consistency with
series_prob; totals parsing against the LIVE-observed Cloudbet key
(`esport_valorant.totals`, LOG entry 30) with kill-total exclusion; the
frozen-record discipline (a totals pick prices only from the frozen
p_maps_dist — rows frozen before that column simply have no totals pick);
EV/CLV arithmetic; the extrapolation label; the pre-registered validation
gate; and the ingest endpoint's auth.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from vpredict import config
from vpredict.modeling.series import series_outcome_dist, series_prob
from vpredict.odds import cloudbet
from vpredict.odds.markets import build_markets_report, build_picks
from vpredict.odds.schema import OddsCapture

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------- series dist

def test_outcome_dist_matches_closed_form_bo3():
    p = 0.6
    d = series_outcome_dist([p] * 3)
    assert d["p_win"] == pytest.approx(series_prob([p] * 3))
    assert d["maps_dist"][2] == pytest.approx(p * p + (1 - p) * (1 - p))
    assert d["maps_dist"][3] == pytest.approx(2 * p * (1 - p))
    assert sum(d["maps_dist"].values()) == pytest.approx(1.0)


def test_outcome_dist_bo5_support_and_mass():
    d = series_outcome_dist([0.55] * 5)
    assert set(d["maps_dist"]) == {3, 4, 5}
    assert sum(d["maps_dist"].values()) == pytest.approx(1.0)
    assert d["p_win"] == pytest.approx(series_prob([0.55] * 5))


# ------------------------------------------------- cloudbet totals parsing

CB_TOTALS_PAYLOAD = {
    "events": [{
        "id": 900, "status": "TRADING",
        "home": {"name": "Team Solid"}, "away": {"name": "Krunker"},
        "startTime": "2026-07-25T12:00:00Z",
        "markets": {
            "esport_valorant.winner": {"submarkets": {"period=ft": {
                "selections": [
                    {"outcome": "home", "params": "", "price": 1.61,
                     "side": "BACK"},
                    {"outcome": "away", "params": "", "price": 2.29,
                     "side": "BACK"}]}}},
            # The key the first live run actually reported — no 'map' in it.
            "esport_valorant.totals": {"submarkets": {
                "period=ft&total=2.5": {"selections": [
                    {"outcome": "over", "params": "total=2.5",
                     "price": 1.85, "side": "BACK"},
                    {"outcome": "under", "params": "total=2.5",
                     "price": 1.87, "side": "BACK"}]}}},
            # Kill totals must be excluded by name AND by the line guard.
            "esport_valorant.map_1_kill_totals": {"submarkets": {
                "total=156.5": {"selections": [
                    {"outcome": "over", "params": "total=156.5",
                     "price": 1.9, "side": "BACK"},
                    {"outcome": "under", "params": "total=156.5",
                     "price": 1.9, "side": "BACK"}]}}},
        },
    }],
}


def test_cloudbet_emits_winner_and_map_totals_not_kill_totals():
    caps, keys = cloudbet.parse_competition_events(CB_TOTALS_PAYLOAD, NOW,
                                                   "freeze")
    by_market = {(c.market, c.line): c for c in caps}
    assert ("series_moneyline", None) in by_market
    tot = by_market[("maps_total", 2.5)]
    assert (tot.price_home, tot.price_away) == (1.85, 1.87)  # over, under
    assert not any(c.line and c.line > 4.5 for c in caps)
    assert "esport_valorant.map_1_kill_totals" in keys       # seen, logged


# ------------------------------------------------------------ picks & EV

def _row(mid="m1", graded=True, team1_won=1, maps_played=3,
         p_model=0.70, dist=None):
    return {"match_id": mid, "team1_name": "Alpha", "team2_name": "Beta",
            "event": "VCT 2026: Pacific Stage 2", "best_of": 3,
            "start_ts": "2026-07-24T08:00:00+00:00",
            "p_model": p_model, "graded": int(graded),
            "team1_won": team1_won, "maps_played": maps_played,
            "p_maps_dist": json.dumps(dist) if dist else None}


def _cap(mid="m1", kind="freeze", market="series_moneyline", line=None,
         ph=1.61, pa=2.40, home_is_t1=True, at=NOW):
    return OddsCapture(captured_at=at, source="cloudbet", capture_kind=kind,
                       market=market, line=line, book_event_id="777",
                       book_home="Alpha", book_away="Beta",
                       price_home=ph, price_away=pa, match_id=mid,
                       book_home_is_team1=home_is_t1)


def test_moneyline_pick_ev_and_clv():
    row = _row()                                    # p_model=0.70, Alpha won
    caps = [_cap(kind="freeze", ph=1.61, pa=2.40),
            _cap(kind="close", ph=1.50, pa=2.60,
                 at=NOW + timedelta(hours=3))]
    picks, _ = build_picks([row], caps)
    assert len(picks) == 1
    p = picks[0]
    # EV(home)=0.7*1.61-1=0.127 > EV(away)=0.3*2.40-1 -> pick home=Alpha.
    assert p["selection"] == "Alpha"
    assert p["ev_pct"] == pytest.approx(12.7, abs=0.01)
    assert p["implied"] == pytest.approx(1 / 1.61, abs=1e-4)
    # Entry 1.61 vs close 1.50: position beat the close by 1.61/1.50-1.
    assert p["clv_pct"] == pytest.approx((1.61 / 1.50 - 1) * 100, abs=0.01)
    assert p["graded"] and p["won"] is True and not p["extrapolated"]


def test_totals_pick_prices_from_frozen_dist_only():
    dist = {"2": 0.52, "3": 0.48}
    row = _row(dist=dist, maps_played=3)
    cap = _cap(market="maps_total", line=2.5, ph=2.10, pa=1.74)
    picks, _ = build_picks([row], [cap])
    assert len(picks) == 1
    p = picks[0]
    # P(over 2.5)=0.48 -> EV(over)=0.48*2.10-1=0.008 > EV(under)=-0.095.
    assert p["selection"] == "over 2.5 maps"
    assert p["p_model"] == pytest.approx(0.48)
    assert p["won"] is True                         # 3 maps played
    # A row frozen BEFORE p_maps_dist existed cannot be priced — the frozen
    # record rules, so the market is skipped rather than recomputed.
    assert build_picks([_row(dist=None)], [cap])[0] == []


def test_extrapolated_pick_labeled_and_excluded_from_aggregates():
    row = _row(p_model=0.95, team1_won=1)           # outside [0.15, 0.88]
    picks, _ = build_picks([row], [_cap(ph=1.05, pa=9.0)])
    assert picks[0]["extrapolated"] is True
    rep = build_markets_report([row], [_cap(ph=1.05, pa=9.0)], now=NOW)
    assert rep["summary"]["n_extrapolated"] == 1
    assert rep["summary"]["avg_ev_pct"] is None     # nothing left to average
    assert rep["summary"]["win_rate"] == 1.0        # win rate still honest


def test_gate_stays_unvalidated_below_threshold():
    rep = build_markets_report([_row()], [_cap()], now=NOW)
    assert rep["gate"]["required"] == config.EV_MIN_GRADED_PICKS
    assert rep["gate"]["ev_validated"] is False
    assert rep["section"] == "LIVE"
    assert "tier1" in rep["by_tier"]


def test_book_priority_prefers_pinnacle_for_headline():
    row = _row()
    cb = _cap(ph=1.61, pa=2.40)
    pn = OddsCapture(captured_at=NOW, source="pinnacle",
                     capture_kind="freeze", book_event_id="9",
                     book_home="Alpha", book_away="Beta",
                     price_home=1.65, price_away=2.35, match_id="m1",
                     book_home_is_team1=True)
    picks, _ = build_picks([row], [cb, pn])
    assert len(picks) == 1 and picks[0]["source"] == "pinnacle"


# --------------------------------------------------------------- ingest API

def test_markets_endpoint_empty_then_ingest_roundtrip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from vpredict.serving.api import create_app
    monkeypatch.setenv("VPREDICT_INGEST_TOKEN", "s3cret")
    c = TestClient(create_app(data_dir=tmp_path))
    empty = c.get("/api/markets").json()
    assert empty["picks"] == [] and empty["gate"]["ev_validated"] is False

    report = {"generated_at": NOW.isoformat(), "picks": [{"x": 1}],
              "gate": {"n_graded": 0, "required": 100,
                       "ev_validated": False}}
    assert c.post("/api/ingest/markets", json=report).status_code == 401
    assert c.post("/api/ingest/markets", json=report,
                  headers={"Authorization": "Bearer wrong"}
                  ).status_code == 401
    ok = c.post("/api/ingest/markets", json=report,
                headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200 and ok.json()["items"] == 1
    assert c.get("/api/markets").json()["picks"] == [{"x": 1}]

    monkeypatch.delenv("VPREDICT_INGEST_TOKEN")
    assert c.post("/api/ingest/markets", json=report,
                  headers={"Authorization": "Bearer s3cret"}
                  ).status_code == 503


def test_totals_ev_excluded_from_aggregates_and_gate():
    """Owner-directed (ASSUMPTIONS §20): maps-total EV carries the measured
    ~7-point independence bias, so totals picks stay visible in the record
    but are labeled, kept out of EV/CLV aggregates, and do not count
    toward the EV validation gate. Moneyline is unaffected."""
    rows = [_row(mid="m1"),
            _row(mid="m2", dist={"2": 0.55, "3": 0.45}, maps_played=2)]
    caps = [_cap(mid="m1", ph=1.61, pa=2.40),
            _cap(mid="m2", market="maps_total", line=2.5, ph=2.10, pa=1.75)]
    rep = build_markets_report(rows, caps)
    by_id = {(p["match_id"], p["market"]): p for p in rep["picks"]}
    ml = by_id[("m1", "series_moneyline")]
    tot = by_id[("m2", "maps_total")]
    assert ml["ev_excluded"] is None
    assert tot["ev_excluded"] == "totals_independence_bias"
    # Gate validates only clean-EV picks; the record keeps both.
    assert rep["gate"]["n_graded"] == 1
    assert rep["summary"]["n_graded"] == 2
    assert rep["summary"]["n_ev_excluded"] == 1
    # Aggregate EV equals the moneyline pick's alone.
    assert rep["summary"]["avg_ev_pct"] == pytest.approx(ml["ev_pct"], abs=0.01)


# ----------------------------------------------------- best-line (ASSUMPTIONS §43)

def _cap_src(source, ph, pa, kind="freeze", hours=0, home_is_t1=True):
    from datetime import timedelta
    return OddsCapture(
        captured_at=NOW + timedelta(hours=hours), source=source,
        capture_kind=kind, market="series_moneyline",
        book_event_id=f"{source}-ev", book_home="RED", book_away="BLU",
        price_home=ph, price_away=pa, match_id="m1",
        book_home_is_team1=home_is_t1, link_method="exact")


def _row_m1(p_model=0.60):
    return {"match_id": "m1", "team1_name": "RED", "team2_name": "BLU",
            "event": "VCT Masters", "start_ts": NOW.isoformat(),
            "p_model": p_model, "best_of": 3, "graded": 0,
            "team1_won": None, "maps_played": None}


def test_best_line_takes_the_better_price_and_names_the_book():
    caps = [_cap_src("cloudbet", 1.95, 1.95),
            _cap_src("pinnacle", 1.83, 2.01)]
    p = build_picks([_row_m1(0.60)], caps)[0][0]
    # model favours home (RED): best home price is cloudbet's 1.95
    assert p["selection"] == "RED"
    assert p["source"] == "cloudbet" and p["price_entry"] == 1.95
    assert p["n_books"] == 2
    assert 0.0 < p["shin_consensus"] < 1.0


def test_clv_uses_entry_books_own_close_only():
    caps = [_cap_src("cloudbet", 1.95, 1.95),
            _cap_src("pinnacle", 1.83, 2.01),
            _cap_src("pinnacle", 1.70, 2.20, kind="close", hours=5)]
    p = build_picks([_row_m1(0.60)], caps)[0][0]
    assert p["source"] == "cloudbet"
    assert p["clv_pct"] is None and p["close_captured"] is False


def test_price_tie_breaks_by_book_priority():
    caps = [_cap_src("cloudbet", 1.90, 1.90),
            _cap_src("pinnacle", 1.90, 1.90)]
    p = build_picks([_row_m1(0.60)], caps)[0][0]
    assert p["source"] == "pinnacle"      # config.ODDS_BOOK_PRIORITY[0]


def test_single_book_parity_with_old_headline_behavior():
    caps = [_cap_src("cloudbet", 1.83, 2.01)]
    p = build_picks([_row_m1(0.60)], caps)[0][0]
    assert p["source"] == "cloudbet" and p["price_entry"] == 1.83
    assert p["shin_consensus"] == p["shin"]
    assert p["n_books"] == 1


def test_gate_counts_one_pick_per_match_market_with_two_books():
    caps = [_cap_src("cloudbet", 1.95, 1.95),
            _cap_src("pinnacle", 1.83, 2.01)]
    row = _row_m1(0.60) | {"graded": 1, "team1_won": 1}
    report = build_markets_report([row], caps)
    assert len(report["picks"]) == 1
    assert report["gate"]["n_graded"] == 1


# ------------------------------------------- unpriceable records (LOG entry 46)

def _row_m(mid, p_model=0.60):
    return {"match_id": mid, "team1_name": "RED", "team2_name": "BLU",
            "event": "VCT Masters", "start_ts": NOW.isoformat(),
            "p_model": p_model, "best_of": 3, "graded": 0,
            "team1_won": None, "maps_played": None}


def _cap_m(mid, source, ph, pa, market="series_moneyline", line=None,
           kind="freeze", hours=0):
    from datetime import timedelta
    return OddsCapture(
        captured_at=NOW + timedelta(hours=hours), source=source,
        capture_kind=kind, market=market, line=line,
        book_event_id=f"{source}-{mid}", book_home="RED", book_away="BLU",
        price_home=ph, price_away=pa, match_id=mid,
        book_home_is_team1=True, link_method="exact")


def test_degenerate_price_skips_that_book_not_the_build():
    picks, sk = build_picks([_row_m("m1")],
                            [_cap_m("m1", "pinnacle", 1.83, 2.01),
                             _cap_m("m1", "cloudbet", 1.0, 13.0)])
    assert len(picks) == 1
    assert picks[0]["source"] == "pinnacle"
    assert picks[0]["n_books"] == 1          # the bad book never priced it
    assert sk["n_unpriceable"] == 1


def test_degenerate_close_becomes_no_close():
    picks, sk = build_picks(
        [_row_m("m1")],
        [_cap_m("m1", "pinnacle", 1.83, 2.01),
         _cap_m("m1", "pinnacle", 1.0, 9.0, kind="close", hours=5)])
    assert picks[0]["close_captured"] is False
    assert picks[0]["clv_pct"] is None
    assert sk["n_unpriceable"] == 1


def test_all_sources_unpriceable_drops_group_with_counter():
    picks, sk = build_picks([_row_m("m1")],
                            [_cap_m("m1", "cloudbet", 1.0, 13.0)])
    assert picks == []
    assert sk["n_unpriceable"] == 1


def test_one_bad_record_cannot_block_other_matches():
    picks, sk = build_picks(
        [_row_m("m1"), _row_m("m2")],
        [_cap_m("m1", "pinnacle", 1.83, 2.01),
         _cap_m("m2", "cloudbet", 1.0, 13.0)])
    assert [p["match_id"] for p in picks] == ["m1"]
    assert sk["n_unpriceable"] == 1


def test_mixed_totals_lines_sort_without_type_error():
    import json as _json
    row = _row_m("m1") | {"p_maps_dist": _json.dumps({"2": 0.55, "3": 0.45})}
    picks, sk = build_picks(
        [row],
        [_cap_m("m1", "pinnacle", 1.9, 1.9, "maps_total", 2.5),
         _cap_m("m1", "pinnacle", 1.9, 1.9, "maps_total", None)])
    # The lined group prices; the lineless one cannot (no line, by design)
    # and must neither crash the sort nor block the lined pick.
    totals = [p for p in picks if p["market"] == "maps_total"]
    assert len(totals) == 1 and totals[0]["line"] == 2.5
    assert sk["n_unpriceable"] == 0
