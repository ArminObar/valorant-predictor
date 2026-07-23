"""Series aggregation tests: exact DP against closed forms, veto parsing."""
from __future__ import annotations

import math

import pytest

from vpredict.modeling.series import complete_sequence, parse_veto, series_prob

MAPS = ["Ascent", "Bind", "Breeze", "Fracture", "Haven", "Lotus", "Pearl", "Split"]


def test_series_prob_bo3_closed_form():
    p1, p2, p3 = 0.62, 0.48, 0.55
    expected = p1 * p2 + p1 * (1 - p2) * p3 + (1 - p1) * p2 * p3
    assert math.isclose(series_prob([p1, p2, p3]), expected, rel_tol=1e-12)


def test_series_prob_symmetry_and_bounds():
    p = [0.62, 0.48, 0.55, 0.51, 0.44]
    q = [1 - x for x in p]
    assert math.isclose(series_prob(p) + series_prob(q), 1.0, rel_tol=1e-12)
    assert math.isclose(series_prob([0.5] * 3), 0.5, rel_tol=1e-12)
    assert series_prob([1.0, 1.0, 0.0]) == 1.0
    with pytest.raises(ValueError):
        series_prob([0.5, 0.5])   # even length is not a best-of


def test_parse_veto_real_format():
    raw = ("TS ban Haven; KRX ban Bind; TS pick Pearl; KRX pick Fracture; "
           "TS ban Breeze; KRX ban Lotus; Split remains")
    assert parse_veto(raw, MAPS) == ["Pearl", "Fracture", "Split"]
    # Case-insensitive canonicalisation against the vocab.
    assert parse_veto("A pick pearl; B pick SPLIT; haven remains", MAPS) == \
        ["Pearl", "Split", "Haven"]
    assert parse_veto("", MAPS) is None
    assert parse_veto("no structure here at all", MAPS) is None


def test_complete_sequence_veto_fill_and_prefix_check():
    raw = ("TS ban Haven; KRX ban Bind; TS pick Pearl; KRX pick Fracture; "
           "TS ban Breeze; KRX ban Lotus; Split remains")
    # 2-0 series: decider recovered from the veto.
    s = complete_sequence(["Pearl", "Fracture"], raw, 3, MAPS)
    assert s.maps == ["Pearl", "Fracture", "Split"]
    assert s.n_filled_from_veto == 1 and s.n_fallback == 0 and s.source == "veto"
    # All maps played: nothing to fill.
    s3 = complete_sequence(["Pearl", "Fracture", "Split"], raw, 3, MAPS)
    assert s3.source == "played" and s3.maps[-1] == "Split"
    # Veto prefix disagreeing with reality -> distrust the veto entirely.
    bad = complete_sequence(["Ascent", "Fracture"], raw, 3, MAPS)
    assert bad.maps == ["Ascent", "Fracture", None]
    assert bad.n_fallback == 1 and bad.source == "fallback"
    # No veto at all -> fallback slot.
    none = complete_sequence(["Pearl", "Fracture"], "", 3, MAPS)
    assert none.maps[-1] is None and none.n_fallback == 1
