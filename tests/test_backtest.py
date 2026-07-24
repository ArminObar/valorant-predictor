"""Walk-forward backtest tests (spec item 7).

The one that matters most: `test_asof_...` pins the leakage rule at the
walk's grain — a decisive match that STARTS before the target's call but
whose ESTIMATED FINISH lands after it must not move the target's
prediction, and the same match finishing earlier must. The rest pin the
production-cadence replay, the BACKTEST/LIVE section discipline (per-tier
metrics only, labels present), the synthetic-data watermark, and the
run-once/--replace gate.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from vpredict.evaluation.backtest import match_table, run_backtest

# Reuse the leakage suite's synthetic map-row builders — same shapes the
# feature pipeline is already tested against.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_leakage import _bo3  # noqa: E402

T0 = pd.Timestamp("2026-01-05T12:00:00Z")
TEAMS = ["red", "blu", "grn"]


def _history(n_matches: int = 16, start: pd.Timestamp = T0,
             gap_hours: int = 30) -> list[dict]:
    """Alternating Bo3s among three teams. Every series goes 2-1 so each
    match contributes BOTH label classes to any fold (a 2-0 series is one
    class per match and can starve tiny validation slices), and every 4th
    series is an UPSET so no validation slice is linearly separable (a
    separable slice makes the Platt calibrator a step function and freezes
    the outputs — a tiny-data artifact, not a production behaviour).
    'red' wins most series, so the walk still has real signal to learn."""
    rows: list[dict] = []
    t = start
    for i in range(n_matches):
        a, b = TEAMS[i % 3], TEAMS[(i + 1) % 3]
        a_wins = (a == "red") or (b != "red")
        if i % 4 == 3:
            a_wins = not a_wins                      # the upset
        scores = [(13, 7), (7, 13), (13, 9)] if a_wins \
            else [(7, 13), (13, 7), (9, 13)]
        rows += _bo3(f"m{i:03d}", t, a, b, scores)
        t = t + pd.Timedelta(hours=gap_hours)
    return rows


def _run(rows, **kw):
    df = pd.DataFrame(rows)
    defaults = dict(warmup_matches=10, tick_hours=6)
    defaults.update(kw)
    return run_backtest(df, **defaults)


def test_walk_produces_ledger_shaped_graded_rows():
    report, rows = _run(_history(16))
    assert report["window"]["n_predictions"] == len(rows) > 0
    r = rows[0]
    for key in ("p_model", "p_elo", "maps_dist", "low_history",
                "model_version", "made_at", "tier", "team1_won",
                "maps_played", "retrain_index"):
        assert key in r
    assert 0.0 < r["p_model"] < 1.0
    assert r["model_version"].startswith("backtest-r")
    # Calls are made at start - freeze margin, strictly before the start.
    assert pd.Timestamp(r["made_at"]) < pd.Timestamp(r["start_ts"])


def test_asof_late_finishing_match_cannot_move_a_call():
    base = _history(16)
    target_id = "m015"                       # the last match in the walk

    _, rows_a = _run(base)
    p_base = [r for r in rows_a if r["match_id"] == target_id][0]["p_model"]

    # An extra blowout between the target's own teams — AGAINST the walk's
    # dominant pattern (blu crushes red), so its influence, when eligible,
    # cannot hide under output rounding — STARTING before the target but
    # with an estimated finish AFTER the target's call time (Bo3 -> 3h
    # assumed duration; target call = its start - 5 min).
    t_start = pd.Timestamp([r for r in rows_a
                            if r["match_id"] == target_id][0]["start_ts"])
    late = _bo3("m900", t_start - pd.Timedelta(hours=1),
                "red", "blu", [(0, 13), (0, 13)])
    _, rows_b = _run(base + late)
    p_late = [r for r in rows_b if r["match_id"] == target_id][0]["p_model"]
    assert p_late == pytest.approx(p_base, abs=1e-12), \
        "a match that had not finished at the call moved the prediction"

    # The same blowout finishing well BEFORE the call must move it.
    early = _bo3("m900", t_start - pd.Timedelta(hours=20),
                 "red", "blu", [(0, 13), (0, 13)])
    _, rows_c = _run(base + early)
    p_early = [r for r in rows_c if r["match_id"] == target_id][0]["p_model"]
    assert p_early != pytest.approx(p_base, abs=1e-9), \
        "an eligible finished match failed to influence the prediction"


def test_cadence_age_trigger_replays_production_rule():
    # 16 matches spread 30h apart span ~19 days after a 10-match warmup:
    # expect the warmup retrain plus at least one 7-day age retrain, with
    # the production trigger strings recorded.
    report, _ = _run(_history(16))
    triggers = [r["trigger"] for r in report["retrains"]]
    assert triggers[0].startswith("warmup")
    assert any("older than" in t for t in triggers[1:])
    assert report["window"]["n_retrains"] == len(report["retrains"])
    # Rows record which bundle called them, monotonically non-decreasing.
    idxs = [r["retrain_index"] for r in _run(_history(16))[1]]
    assert idxs == sorted(idxs)


def test_section_discipline_per_tier_only_and_labels():
    report, _ = _run(_history(16))
    assert report["section"] == "BACKTEST"
    assert "not independently verifiable" in report["label"]
    assert "never merged" in report["label"]
    # Metrics live per tier ONLY — no pooled metrics block at the top level.
    assert "model_ll" not in report and "elo_ll" not in report
    assert set(report["per_tier"]) == {"other"}      # "Synthetic Cup"
    m = report["per_tier"]["other"]
    assert m["n_scored"] > 0 and 0 < m["model_ll"] and 0 < m["elo_ll"]
    # The stationarity split exists, is per tier, and its cells carry the
    # same metric keys; retrain entries record the calibrator they fitted.
    periods = report["per_tier_by_period"]["other"]
    assert periods and all("model_ll" in v for v in periods.values())
    assert all("calibrator" in r and "n_val_rows" in r
               for r in report["retrains"])
    # The synthetic-data policy: fabricated inputs watermark the report.
    assert report["synthetic_data"] is True


def test_match_table_derivation():
    mt = match_table(pd.DataFrame(_history(4)))
    assert len(mt) == 4
    row = mt.iloc[0]
    assert row["team1_won"] in (0, 1) and row["decided"]
    assert row["maps_played"] == 3
    assert row["est_end_ts"] > row["start_ts"]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "backtest_script", Path(__file__).resolve().parents[1] /
        "scripts" / "backtest.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backtest_script"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_once_gate_semantics():
    gate = _load_script().replace_gate
    ok, _ = gate(None, "v1", replace=False)
    assert ok                                        # first run
    ok, msg = gate({"live_bundle_version": "v1"}, "v1", replace=False)
    assert not ok and "run-once" in msg              # result stands
    ok, msg = gate({"live_bundle_version": "v1"}, "v1", replace=True)
    assert not ok and "unchanged" in msg             # same model: refused
    ok, msg = gate({"live_bundle_version": "v1"}, "v2", replace=True)
    assert ok and "model changed" in msg             # new model: allowed
