"""Measurement wiring (PATCH_NOTES edits C/D/E) — the knobs memharness.py
relies on. Each is a measurement aid, never set in production; these tests pin
the contract the harness assumes and, for the store limit, the one destructive
interaction it must never have.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vpredict.serving import refresh as refresh_mod

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------ edit C: force-retrain knob

def test_force_retrain_env_short_circuits(monkeypatch):
    monkeypatch.setenv("VPREDICT_FORCE_RETRAIN", "1")
    retrain, why = refresh_mod._needs_retrain(NOW)
    assert retrain is True
    assert why.startswith("forced")


def test_force_retrain_off_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("VPREDICT_FORCE_RETRAIN", raising=False)
    from vpredict import config
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)  # no bundle on disk
    retrain, why = refresh_mod._needs_retrain(NOW)
    assert retrain is True and why == "no bundle"  # normal path, not "forced"


# ------------------------------------------------- edit D: store size limit

def _mk(mid: str, days_ago: int):
    from vpredict.data.schema import Match
    return Match(match_id=mid, start_ts=NOW - timedelta(days=days_ago),
                 status="completed")


def test_store_limit_keeps_chronologically_first_n(monkeypatch, tmp_path):
    from vpredict.data import store
    p = tmp_path / "m.jsonl"
    store.upsert_matches([_mk("new", 1), _mk("old", 9), _mk("mid", 5)], path=p)
    monkeypatch.setenv("VPREDICT_STORE_LIMIT", "2")
    got = store.load_matches(p)
    assert [m.match_id for m in got] == ["old", "mid"]


def test_store_limit_never_truncates_via_upsert(monkeypatch, tmp_path):
    """THE destructive interaction the split reader exists to prevent: upsert
    rewrites the file from what it read, so it must read uncapped even when
    the limit env var is set."""
    from vpredict.data import store
    p = tmp_path / "m.jsonl"
    store.upsert_matches([_mk("a", 9), _mk("b", 5), _mk("c", 1)], path=p)
    monkeypatch.setenv("VPREDICT_STORE_LIMIT", "1")
    store.upsert_matches([_mk("d", 0)], path=p)  # would truncate if buggy
    monkeypatch.delenv("VPREDICT_STORE_LIMIT")
    assert {m.match_id for m in store.load_matches(p)} == {"a", "b", "c", "d"}


# ---------------------------------------------- edit E: workspace re-rooting

def test_workspace_env_reroots_all_data_paths(tmp_path):
    """config computes paths at import time, so exercise it in a fresh
    interpreter. VPREDICT_WORKSPACE must win over VPREDICT_DATA."""
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env["VPREDICT_WORKSPACE"] = str(tmp_path)
    env["VPREDICT_DATA"] = "/definitely/not/used"
    code = (
        "from vpredict import config; "
        "print(config.MATCHES_JSONL); print(config.MODELS_DIR); "
        "print(config.LEDGER_PATH)"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, check=True).stdout
    lines = out.strip().splitlines()
    assert all(line.startswith(str(tmp_path)) for line in lines), lines
    assert "/definitely/not/used" not in out
