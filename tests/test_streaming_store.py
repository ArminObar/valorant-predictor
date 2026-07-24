"""The streaming store contract (memory trim, LOG entry 23).

The refresh cycle must never materialize the full store: iter_matches streams,
grade consumes a stream against a small id set, and upsert is a sorted merge
with memory O(batch). These tests pin the semantics the old materializing
implementations had, plus the two invariants the trim introduces: the store
file stays sorted by (start_ts, match_id), and pass-through lines are never
re-validated.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from vpredict.data import store
from vpredict.data.schema import Match
from vpredict.serving.ledger import Ledger

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _m(mid: str, days_ago: float, status: str = "completed",
       winner: str | None = "team1", best_of: int = 3) -> Match:
    return Match(match_id=mid, start_ts=NOW - timedelta(days=days_ago),
                 status=status, winner=winner, best_of=best_of)


def _ids_in_file(path) -> list[str]:
    return [json.loads(line)["match_id"]
            for line in path.read_text().splitlines() if line.strip()]


# ------------------------------------------------------------------- upsert

def test_upsert_insert_and_sorted_file(tmp_path):
    p = tmp_path / "m.jsonl"
    assert store.upsert_matches([_m("b", 5), _m("c", 1)], path=p) == 2
    # merging an OLDER match must land at the front, keeping the file sorted
    assert store.upsert_matches([_m("a", 9)], path=p) == 1
    assert _ids_in_file(p) == ["a", "b", "c"]


def test_upsert_collision_semantics(tmp_path):
    p = tmp_path / "m.jsonl"
    store.upsert_matches([_m("a", 9), _m("b", 5)], path=p)
    # identical record -> not counted as changed, file untouched semantically
    assert store.upsert_matches([_m("a", 9)], path=p) == 0
    # modified record (winner flips) -> counted, replaced in place
    assert store.upsert_matches([_m("a", 9, winner="team2")], path=p) == 1
    got = {m.match_id: m for m in store.load_matches(p)}
    assert got["a"].winner == "team2" and len(got) == 2


def test_upsert_replacement_with_moved_timestamp_stays_sorted(tmp_path):
    p = tmp_path / "m.jsonl"
    store.upsert_matches([_m("a", 9), _m("b", 5), _m("c", 1)], path=p)
    # "b" moves to the newest position -> must merge to the tail, not sit
    # where the old line was
    assert store.upsert_matches([_m("b", 0.5)], path=p) == 1
    assert _ids_in_file(p) == ["a", "c", "b"]
    keys = [(m.start_ts, m.match_id) for m in store.load_matches(p)]
    assert keys == sorted(keys)


def test_upsert_never_validates_passthrough_lines(tmp_path, monkeypatch):
    """The memory point of the merge: untouched lines are copied verbatim.
    Only colliding lines may be parsed into Match (for the changed-count
    comparison)."""
    p = tmp_path / "m.jsonl"
    store.upsert_matches([_m(f"m{i}", 9 - i) for i in range(6)], path=p)

    calls = {"n": 0}
    real = Match.model_validate_json.__func__

    def counting(cls, *a, **k):
        calls["n"] += 1
        return real(cls, *a, **k)

    monkeypatch.setattr(Match, "model_validate_json", classmethod(counting))
    store.upsert_matches([_m("m2", 7, winner="team2"), _m("new", 0)], path=p)
    assert calls["n"] == 1  # exactly the one colliding line


# --------------------------------------------------------------- iter/count

def test_iter_matches_matches_load(tmp_path):
    p = tmp_path / "m.jsonl"
    store.upsert_matches([_m("a", 9), _m("b", 5), _m("c", 1)], path=p)
    assert ([m.match_id for m in store.iter_matches(p)]
            == [m.match_id for m in store.load_matches(p)]
            == ["a", "b", "c"])


def test_count_matches_plain_and_capped(tmp_path, monkeypatch):
    p = tmp_path / "m.jsonl"
    assert store.count_matches(p) == 0
    store.upsert_matches([_m("a", 9), _m("b", 5), _m("c", 1)], path=p)
    assert store.count_matches(p) == 3
    monkeypatch.setenv("VPREDICT_STORE_LIMIT", "2")
    assert store.count_matches(p) == 2


# ------------------------------------------------------------ streamed grade

def test_grade_consumes_a_generator(tmp_path):
    led = Ledger(tmp_path / "ledger.sqlite")
    led.insert_prediction(
        match_id="g1", start_ts=NOW + timedelta(hours=2),
        team1="a", team2="b", team1_name="A", team2_name="B",
        event="E", best_of=3, p_model=0.7, p_elo=0.6,
        model_version="v1", now=NOW)

    def stream():
        yield _m("other", 3)
        yield _m("g1", 2, winner="team2")

    assert led.grade(stream(), now=NOW) == 1
    row = led.rows(graded=True)[0]
    assert row["match_id"] == "g1" and row["team1_won"] == 0
    led.close()


# ---------------------------------------------------------- -m entrypoint

def test_refresh_module_entrypoint_runs_as_subprocess(tmp_path):
    """The scheduler spawns `python -m vpredict.serving.refresh`; that
    entrypoint must exist and produce the cycle JSON even on an empty
    workspace (train fails loudly inside its fault isolation)."""
    env = {"VPREDICT_WORKSPACE": str(tmp_path), "PATH": "/usr/bin:/bin"}
    import os
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    proc = subprocess.run(
        [sys.executable, "-m", "vpredict.serving.refresh", "--no-crawl"],
        capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert {"ts", "graded", "retrain"} <= set(out)
    assert "error" in out.get("train", {})  # empty store -> loud failure
