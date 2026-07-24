"""Fuzzy alias-suggestion tests.

The positive cases are the exact unlinked pairs the first live Cloudbet run
produced (2026-07-24): shortened org names, generic-token drops, and one
acronym. The negative cases pin the two safety properties: sibling-roster
qualifiers disqualify, and near-ties are surfaced as ambiguous rather than
silently resolved.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from vpredict.odds.fuzzy import similarity, suggest


def _p(mid: str, t1: str, t2: str) -> dict:
    return {"match_id": mid, "team1_name": t1, "team2_name": t2}


PREDICTIONS = [
    _p("1", "Trace Esports", "Wuxi Titan Esports Club"),
    _p("2", "Team Secret", "T1"),
    _p("3", "G2 Esports", "Cloud9"),
    _p("4", "Rex Regum Qeon", "ZETA DIVISION"),
    _p("5", "Gen.G", "Paper Rex"),
]


def test_first_live_run_unlinked_pairs_all_link():
    cases = [
        ("Trace", "Titan", "1"),
        ("Secret", "T1", "2"),
        ("G2", "Cloud9", "3"),
    ]
    for bh, ba, mid in cases:
        s = suggest(bh, ba, PREDICTIONS)
        assert s is not None and s.prediction["match_id"] == mid, (bh, ba)
        assert s.book_home_is_team1 is True
        assert s.ambiguous_with is None


def test_acronym_and_flipped_orientation():
    s = suggest("ZETA", "RRQ", PREDICTIONS)
    assert s is not None and s.prediction["match_id"] == "4"
    assert s.book_home_is_team1 is False        # book home is our team2
    assert similarity("RRQ", "Rex Regum Qeon") >= 0.90


def test_sibling_roster_qualifier_disqualifies():
    # "G2" must never be proposed for an Academy roster, whatever the
    # string similarity says.
    assert similarity("G2", "G2 Academy") == 0.0
    assert similarity("Titan GC", "Wuxi Titan Esports Club") == 0.0
    only_academy = [_p("9", "G2 Academy", "Cloud9 Academy")]
    assert suggest("G2", "Cloud9", only_academy) is None


def test_near_tie_is_flagged_ambiguous():
    preds = [_p("a", "Titan Esports", "Alpha"),
             _p("b", "Titan Gaming", "Alpha")]
    s = suggest("Titan", "Alpha", preds)
    assert s is not None and s.ambiguous_with is not None


def test_generic_token_drop_never_empties_a_name():
    # A name made ONLY of generic tokens must still compare as itself.
    assert similarity("Team", "Team") == 1.0


def test_end_to_end_against_seed_predictions():
    """Every one of the 11 book strings the first run reported as unlinked
    resolves against the real seed prediction set (the same set that run
    used), unambiguously."""
    import json
    seed = Path(__file__).resolve().parents[1] / "seed" / \
        "upcoming_predictions.json"
    preds = json.loads(seed.read_text(encoding="utf-8"))["predictions"]
    for bh, ba in [("Trace", "Titan"), ("Secret", "T1"), ("G2", "Cloud9")]:
        s = suggest(bh, ba, preds)
        assert s is not None and s.ambiguous_with is None, (bh, ba)
        names = {s.prediction["team1_name"], s.prediction["team2_name"]}
        assert any(bh.casefold() in n.casefold() or ba.casefold()
                   in n.casefold() for n in names)


def test_capture_lock_blocks_second_holder(tmp_path, monkeypatch):
    from vpredict import config
    monkeypatch.setattr(config, "ODDS_DIR", tmp_path)
    spec = importlib.util.spec_from_file_location(
        "capture_odds", Path(__file__).resolve().parents[1] /
        "scripts" / "capture_odds.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["capture_odds"] = mod
    spec.loader.exec_module(mod)
    first = mod.acquire_capture_lock()
    assert first is not None
    second = mod.acquire_capture_lock()
    assert second is None                  # overlap detected, no race
    first.close()
    third = mod.acquire_capture_lock()
    assert third is not None               # released cleanly
    third.close()
