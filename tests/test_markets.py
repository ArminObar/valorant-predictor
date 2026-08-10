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

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


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

def test_markets_is_server_authoritative_and_legacy_route_is_gone(
        tmp_path, monkeypatch):
    """ASSUMPTIONS §65: the in-process refresh build is the only writer of
    markets.json. The legacy Mac-push route is removed, so a surviving
    publish job fails loudly instead of silently replacing the fresh
    build; the read endpoint serves whatever the build wrote, builder
    stamp included."""
    import json as _json

    from fastapi.testclient import TestClient
    from vpredict.serving.api import create_app
    monkeypatch.setenv("VPREDICT_INGEST_TOKEN", "s3cret")
    c = TestClient(create_app(data_dir=tmp_path))
    empty = c.get("/api/markets").json()
    assert empty["picks"] == [] and empty["gate"]["ev_validated"] is False

    report = {"generated_at": NOW.isoformat(), "picks": [{"x": 1}],
              "gate": {"n_graded": 0, "required": 100,
                       "ev_validated": False}}
    # Even a correctly-authenticated legacy push must fail now.
    # 405 not 404: the SPA fallback owns unknown GET paths, so a POST to
    # the removed route hits method-not-allowed. Either way: no write.
    assert c.post("/api/ingest/markets", json=report,
                  headers={"Authorization": "Bearer s3cret"}
                  ).status_code in (404, 405)
    assert not (tmp_path / "processed" / "markets.json").exists()

    proc = tmp_path / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    (proc / "markets.json").write_text(_json.dumps(
        {**report, "builder": "server-refresh"}))
    got = c.get("/api/markets").json()
    assert got["picks"] == [{"x": 1}]
    assert got["builder"] == "server-refresh"


def test_report_carries_builder_provenance():
    r = build_markets_report([], [])
    assert r["builder"] == "server-refresh"


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


# --------------------------------------- priceability + isolation (LOG entry 47)

def test_zero_negative_and_inf_prices_are_all_skipped():
    picks, sk = build_picks(
        [_row_m("m1")],
        [_cap_m("m1", "pinnacle", 1.83, 2.01),
         _cap_m("m1", "cloudbet", 0.0, 0.0),
         _cap_m("m1", "cloudbet", -1.5, 2.0, hours=1),
         _cap_m("m1", "cloudbet", float("inf"), 2.0, hours=2)])
    assert len(picks) == 1 and picks[0]["source"] == "pinnacle"
    assert sk["n_unpriceable"] == 3 and sk["n_group_errors"] == 0


def test_nan_prices_are_skipped_not_emitted():
    picks, sk = build_picks(
        [_row_m("m1")],
        [_cap_m("m1", "pinnacle", float("nan"), float("nan"))])
    assert picks == []
    assert sk["n_unpriceable"] == 1


def test_entry_falls_back_to_first_priceable_freeze():
    picks, sk = build_picks(
        [_row_m("m1")],
        [_cap_m("m1", "pinnacle", 0.0, 0.0),            # placeholder first
         _cap_m("m1", "pinnacle", 1.83, 2.01, hours=1)])
    assert len(picks) == 1
    from datetime import timedelta
    assert picks[0]["price_entry"] in (1.83, 2.01)
    assert picks[0]["entry_captured_at"] == (NOW
                                             + timedelta(hours=1)).isoformat()
    assert sk["n_unpriceable"] == 1


def test_unlinked_degenerate_records_neither_crash_nor_count():
    from vpredict.odds.schema import OddsCapture as OC
    stray = OC(captured_at=NOW, source="cloudbet", capture_kind="freeze",
               book_event_id="x", book_home="Who", book_away="Ever",
               price_home=0.0, price_away=0.0)
    picks, sk = build_picks([_row_m("m1")],
                            [stray, _cap_m("m1", "pinnacle", 1.83, 2.01)])
    assert len(picks) == 1
    assert sk["n_unpriceable"] == 0          # never part of the build


def test_group_error_is_isolated_counted_and_logged(monkeypatch, caplog):
    import vpredict.odds.markets as mk

    real = mk._grade

    def boom(row, *a, **k):
        # signature-agnostic passthrough: the test injects a failure, it
        # must not care about _grade's arity
        if row["match_id"] == "m2":
            raise RuntimeError("synthetic group failure")
        return real(row, *a, **k)

    monkeypatch.setattr(mk, "_grade", boom)
    with caplog.at_level("ERROR", logger="vpredict.markets"):
        picks, sk = build_picks(
            [_row_m("m1"), _row_m("m2")],
            [_cap_m("m1", "pinnacle", 1.83, 2.01),
             _cap_m("m2", "pinnacle", 1.83, 2.01)])
    assert [p["match_id"] for p in picks] == ["m1"]
    assert sk["n_group_errors"] == 1
    assert "pick group" in caplog.text and "m2" in caplog.text


# ------------------------------------ canonical sides (LOG entry 55)
# Every fixture above lists both books in the same home/away order, which is
# exactly why the orientation scramble survived: comparing sides by book
# label only breaks when books disagree. These fixtures disagree.

def test_opposite_book_orientations_select_the_true_best_side():
    # Cloudbet lists RED-BLU, Pinnacle lists BLU-RED. Under by-label
    # comparison RED never entered the menu and the pick came out
    # BLU@2.55 (EV -3.1%); the true best of the four options is
    # RED@1.60 at -0.8%.
    caps = [_cap_src("cloudbet", 1.60, 2.40, home_is_t1=True),
            _cap_src("pinnacle", 2.55, 1.58, home_is_t1=False)]
    p = build_picks([_row_m1(0.62)], caps)[0][0]
    assert p["selection"] == "RED"
    assert p["source"] == "cloudbet" and p["price_entry"] == 1.60
    assert p["ev_pct"] == pytest.approx(-0.8, abs=0.01)
    assert p["n_books"] == 2
    # Negative-EV picks still ship: max-EV selection is the recorded
    # semantics (owner call, ASSUMPTIONS §56); the display labels it.


def test_opposite_book_orientations_consensus_is_same_team_only():
    # Each book's shin contribution is indexed through that book's OWN
    # orientation, so the consensus is a median of the SAME team's fair
    # probabilities (~0.604 and ~0.620 here), never a favourite/underdog
    # mix (which displayed ~0.492 for a ~0.38 side).
    caps = [_cap_src("cloudbet", 1.60, 2.40, home_is_t1=True),
            _cap_src("pinnacle", 2.55, 1.58, home_is_t1=False)]
    p = build_picks([_row_m1(0.62)], caps)[0][0]
    assert 0.60 < p["shin_consensus"] < 0.63
    assert abs(p["shin_consensus"] - p["shin"]) < 0.02


def test_flipped_single_book_names_prices_and_grades_correctly():
    # One book listing BLU first: prices, selection name, implied and the
    # grade must all follow the linked orientation, not the listing order.
    row = _row(p_model=0.62)                       # Alpha won, graded
    cap = _cap(ph=2.55, pa=1.58, home_is_t1=False)  # home=Beta@2.55
    p = build_picks([row], [cap])[0][0]
    assert p["selection"] == "Alpha"
    assert p["price_entry"] == 1.58
    assert p["implied"] == pytest.approx(1 / 1.58, abs=1e-4)
    assert p["won"] is True


def test_close_capture_maps_through_its_own_orientation_for_clv():
    # A book that flips its listing between entry and close still grades
    # the same team's price: entry RED@1.60 (home), close lists BLU first
    # so RED's close price sits in price_away.
    caps = [_cap_src("cloudbet", 1.60, 2.40, home_is_t1=True),
            _cap_src("cloudbet", 2.20, 1.55, kind="close", hours=3,
                     home_is_t1=False)]
    p = build_picks([_row_m1(0.62)], caps)[0][0]
    assert p["selection"] == "RED" and p["close_captured"] is True
    assert p["clv_pct"] == pytest.approx((1.60 / 1.55 - 1) * 100, abs=0.01)


# --------------------------------------- close-only groups (LOG entry 59)

def test_close_only_group_reports_no_clv_not_fabricated_zero():
    """No true freeze exists: entry falls back to the close, so
    price/close_price is identically 1. That is not a measurement of
    zero movement and must not ship as CLV +0.00 (LOG entry 59)."""
    caps = [_cap(kind="close", ph=1.80, pa=2.02,
                 at=NOW + timedelta(hours=3))]
    p = build_picks([_row()], caps)[0][0]
    assert p["entry_kind"] == "close"
    assert p["close_captured"] is True
    assert p["clv_pct"] is None
    assert p["price_entry"] == pytest.approx(1.80)


def test_true_zero_movement_still_reports_zero_clv():
    """A genuine unchanged line between a real freeze and the close is a
    measurement and keeps its honest 0.0."""
    caps = [_cap(kind="freeze", ph=1.61, pa=2.40),
            _cap(kind="close", ph=1.61, pa=2.40,
                 at=NOW + timedelta(hours=3))]
    p = build_picks([_row()], caps)[0][0]
    assert p["entry_kind"] == "freeze"
    assert p["clv_pct"] == pytest.approx(0.0, abs=1e-9)


def test_all_orientations_unlinked_group_is_counted_not_silent():
    """A match with real captured prices but no linked orientation used to
    vanish from Markets without a trace (LOG entry 61)."""
    cap = _cap(home_is_t1=None)
    picks, skipped = build_picks([_row()], [cap])
    assert picks == []
    assert skipped["n_groups_unpriced"] == 1


# ---- patch 0085: unorientable entries, parity, and the era gate (§69)

def _cap85(kind, days_before, ph, pa, orient=True, start=None,
           source="cloudbet"):
    start = start or datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    return OddsCapture(
        captured_at=start - timedelta(days=days_before), source=source,
        capture_kind=kind, book_event_id="e85", book_home="Alpha",
        book_away="Beta", book_start_ts=start, price_home=ph,
        price_away=pa, match_id="m85",
        book_home_is_team1=(True if orient else None),
        link_method="exact")


def _row85(start=None):
    start = start or datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    return {"match_id": "m85", "team1_name": "Alpha",
            "team2_name": "Beta", "start_ts": start.isoformat(),
            "event": "VCT", "best_of": 3, "p_model": 0.31, "p_elo": 0.4,
            "low_history": 0, "graded": 1, "team1_won": 0,
            "p_maps_dist": None, "maps_played": 2}


def test_unorientable_freeze_no_longer_unprices_the_match():
    """LOG 63 regression: the restored-era profile — unoriented freeze
    plus oriented close — must price via the oriented close, entry
    reused as close, CLV honestly None (LOG 59), the set-aside row
    counted."""
    caps = [_cap85("freeze", 3, 1.36, 3.17, orient=False),
            _cap85("close", 0.01, 1.40, 3.00)]
    rep = build_markets_report([_row85()], caps)
    assert len(rep["picks"]) == 1
    p = rep["picks"][0]
    assert p["entry_kind"] == "close" and p["clv_pct"] is None
    assert rep["skipped"]["n_entries_unorientable"] == 1
    assert rep["skipped"]["n_groups_unpriced"] == 0


def test_oriented_later_freeze_becomes_the_entry():
    caps = [_cap85("freeze", 3, 1.36, 3.17, orient=False),
            _cap85("freeze", 2, 1.38, 3.10),
            _cap85("close", 0.01, 1.40, 3.00)]
    rep = build_markets_report([_row85()], caps)
    p = rep["picks"][0]
    assert p["entry_kind"] == "freeze"
    assert p["clv_pct"] is not None
    assert rep["skipped"]["n_entries_unorientable"] == 1


def test_all_unoriented_still_counts_unpriced_not_an_error():
    caps = [_cap85("freeze", 3, 1.36, 3.17, orient=False)]
    rep = build_markets_report([_row85()], caps)
    assert rep["picks"] == []
    assert rep["skipped"]["n_groups_unpriced"] == 1
    assert rep["skipped"]["n_group_errors"] == 0


def test_audit_and_build_agree_on_every_orientation_profile():
    """The parity pin (§69): any match holding at least one oriented
    priceable moneyline row must be COVERED by the build — the audit's
    bug bucket stays empty by construction, and the all-unoriented case
    lands in the orientation bucket, never in 2c."""
    from vpredict.odds.coverage_audit import classify
    profiles = {
        "unoriented freeze + oriented close":
            [_cap85("freeze", 3, 1.36, 3.17, orient=False),
             _cap85("close", 0.01, 1.40, 3.00)],
        "oriented freeze only": [_cap85("freeze", 3, 1.36, 3.17)],
        "close only": [_cap85("close", 0.01, 1.36, 3.17)],
        "all unoriented": [_cap85("freeze", 3, 1.36, 3.17, orient=False)],
    }
    for name, caps in profiles.items():
        rep = build_markets_report([_row85()], caps)
        res = classify([_row85()], caps, rep["picks"], {})
        assert res["buckets"].get("2c_unexplained", []) == [], name
        if name == "all unoriented":
            assert [m["mid"] for m in
                    res["buckets"].get("2b_orientation_missing", [])] == ["m85"]
        else:
            assert [m["mid"] for m in
                    res["buckets"].get("1_covered", [])] == ["m85"], name


def test_pre_markets_era_picks_are_labeled_and_out_of_the_gate():
    """§69: an entry captured before the first possible public markets
    build is shown, labeled, and excluded from the validation gate; a
    post-boundary pick counts normally."""
    early_start = datetime(2026, 7, 24, 20, 0, tzinfo=timezone.utc)
    late_start = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    row_e = dict(_row85(early_start), match_id="mE",
                 team1_name="E1", team2_name="E2")
    row_l = dict(_row85(late_start), match_id="mL",
                 team1_name="L1", team2_name="L2")
    cap_e = OddsCapture(
        captured_at=early_start - timedelta(hours=6), source="cloudbet",
        capture_kind="freeze", book_event_id="eE", book_home="E1",
        book_away="E2", book_start_ts=early_start, price_home=1.8,
        price_away=2.0, match_id="mE", book_home_is_team1=True,
        link_method="exact")
    cap_l = _cap85("freeze", 0.25, 1.8, 2.0, start=late_start)
    cap_l.match_id = "mL"
    cap_l.book_home = "L1"
    cap_l.book_away = "L2"
    rep = build_markets_report([row_e, row_l], [cap_e, cap_l])
    by_id = {p["match_id"]: p for p in rep["picks"]}
    assert by_id["mE"]["pre_markets_era"] is True
    assert by_id["mE"]["ev_excluded"] == "pre_markets_era"
    assert by_id["mL"]["pre_markets_era"] is False
    assert rep["gate"]["n_graded"] == 1
    assert rep["summary"]["n_pre_markets_era"] == 1
