"""Placeholder (TBD) resolution regressions (LOG entry 58, §57).

Three properties:
- A placeholder key is not an identity: `_names_for_row` adopts the
  listing's identity for a placeholder side (anchored on the real key),
  and only a REAL key mismatch falls back to frozen names.
- `resolve_placeholder_names` heals a frozen row's metadata — keys and
  display names only — and can never touch the call or overwrite a real
  key, in either direction.
- Half-resolved slots ("X vs TBD") no longer freeze junk calls; frozen
  ones heal at publish time through the real run_predictions path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vpredict.data.schema import Match
from vpredict.modeling.predict import _names_for_row, run_predictions
from vpredict.serving.ledger import Ledger

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class _Listing:
    def __init__(self, k1, k2, n1, n2):
        self._k = {"team1": k1, "team2": k2}
        self.team1_name, self.team2_name = n1, n2

    def key_team(self, which):
        return self._k[which]


def test_placeholder_side_adopts_listing_identity_all_orientations():
    # frozen: real 15072 first, placeholder second (the 715116 shape)
    row = {"team1": "15072", "team2": "tbd",
           "team1_name": "2Game Esports", "team2_name": "TBD"}
    assert _names_for_row(row, _Listing("15072", "9353", "2Game", "Shopify")) \
        == ("2Game", "Shopify", "15072", "9353", "resolved")
    # listing flipped: the real key anchors orientation
    assert _names_for_row(row, _Listing("9353", "15072", "Shopify", "2Game")) \
        == ("2Game", "Shopify", "15072", "9353", "resolved")
    # frozen: placeholder first (the 715115 shape)
    row2 = {"team1": "tbd", "team2": "9353",
            "team1_name": "TBD", "team2_name": "Shopify Rebellion Black"}
    assert _names_for_row(row2, _Listing("111", "9353", "MIBR GC", "Shopify")) \
        == ("MIBR GC", "Shopify", "111", "9353", "resolved")
    assert _names_for_row(row2, _Listing("9353", "111", "Shopify", "MIBR GC")) \
        == ("MIBR GC", "Shopify", "111", "9353", "resolved")
    # both placeholders: adopt as listed (frozen call is a flagged
    # self-vs-self placeholder; nothing anchors orientation)
    row3 = {"team1": "tbd", "team2": "tbd",
            "team1_name": "TBD", "team2_name": "TBD"}
    assert _names_for_row(row3, _Listing("a", "b", "Alpha", "Bravo")) \
        == ("Alpha", "Bravo", "a", "b", "resolved")
    # placeholder present but the REAL side's key vanished too: frozen
    # names, no guessing
    assert _names_for_row(row, _Listing("777", "888", "X", "Y")) \
        == ("2Game Esports", "TBD", "15072", "tbd", "unmatched")


def _insert(led, mid, k1, k2, n1, n2, start):
    led.insert_prediction(
        match_id=mid, start_ts=start, team1=k1, team2=k2,
        team1_name=n1, team2_name=n2, event="GC Champions", best_of=3,
        p_model=0.5, p_elo=0.5, model_version="vt", low_history=True,
        now=NOW - timedelta(hours=2))


def test_resolve_placeholder_names_heals_metadata_only(tmp_path):
    led = Ledger(tmp_path / "ledger.sqlite")
    _insert(led, "715116", "15072", "tbd", "2Game Esports", "TBD",
            NOW + timedelta(hours=3))
    before = {r["match_id"]: r for r in led.rows(graded=None)}["715116"]

    assert led.resolve_placeholder_names(
        "715116", "15072", "9353", "2Game Esports", "Shopify Rebellion GC")
    after = {r["match_id"]: r for r in led.rows(graded=None)}["715116"]
    assert (after["team2"], after["team2_name"]) == ("9353",
                                                     "Shopify Rebellion GC")
    assert (after["team1"], after["team1_name"]) == ("15072", "2Game Esports")
    # the call is untouched
    for col in ("p_model", "p_elo", "model_version", "made_at", "start_ts",
                "graded", "low_history"):
        assert after[col] == before[col]
    # idempotent: nothing left to heal
    assert not led.resolve_placeholder_names(
        "715116", "15072", "9353", "2Game Esports", "Shopify Rebellion GC")
    # a real key is never overwritten, and a placeholder is never adopted
    assert not led.resolve_placeholder_names(
        "715116", "999", "tbd", "Imposter", "TBD")
    unchanged = {r["match_id"]: r for r in led.rows(graded=None)}["715116"]
    assert unchanged["team1"] == "15072" and unchanged["team2"] == "9353"


def _match(mid, k1, k2, n1, n2, start):
    return Match(match_id=mid, start_ts=start, status="upcoming",
                 best_of=3, event="GC Champions",
                 team1_id=k1, team1_name=n1, team2_id=k2, team2_name=n2)


def test_half_resolved_slots_skip_and_frozen_rows_heal_end_to_end(tmp_path):
    """The real run_predictions path: an 'X vs TBD' listing must not
    freeze a call, and an already-frozen placeholder row must publish and
    heal with the resolved identities once the listing resolves."""
    led = Ledger(tmp_path / "serving" / "ledger.sqlite")
    _insert(led, "715116", "15072", "tbd", "2Game Esports", "TBD",
            NOW + timedelta(hours=3))

    upcoming = [
        # frozen row's match, now fully resolved on the listing
        _match("715116", "15072", "9353", "2Game Esports",
               "Shopify Rebellion GC", NOW + timedelta(hours=3)),
        # a NEW half-resolved slot: must be skipped, not frozen
        _match("715117", "", "4915", "TBD", "Team Liquid GC",
               NOW + timedelta(hours=6)),
    ]
    # key_team falls back to the normalized name for missing ids, so the
    # TBD side of 715117 keys to "tbd" — the guard must catch it.
    assert upcoming[1].key_team("team1") == "tbd"

    out = tmp_path / "up.json"
    # Steady state: a previous payload exists (as on any running server),
    # so the frozen row's display extras carry forward instead of forcing
    # the engine recompute path, which needs real history.
    import json
    out.write_text(json.dumps({
        "predictions": [{"match_id": "715116",
                         "per_map": {"Ascent": 0.5},
                         "per_map_elo": {"Ascent": 0}}],
        "pool": ["Ascent"]}))
    counters = run_predictions({"version": "vt"}, history=None,
                               upcoming=upcoming, ledger=led, now=NOW,
                               json_path=out)
    assert counters["skipped_placeholder"] == 1
    assert counters["names_resolved"] == 1
    assert counters["ledger_names_resolved"] == 1

    payload = json.loads(out.read_text())
    assert payload["naming"] == {"resolved": ["715116"]}
    pub = {p["match_id"]: p for p in payload["predictions"]}
    assert "715117" in pub or True  # skipped slots are simply absent
    assert len(payload["predictions"]) == 1
    row = pub["715116"]
    assert (row["team1_name"], row["team2_name"]) == (
        "2Game Esports", "Shopify Rebellion GC")
    assert (row["team1"], row["team2"]) == ("15072", "9353")
    assert row["name_status"] == "resolved"
    # and the ledger itself healed
    healed = {r["match_id"]: r for r in led.rows(graded=None)}["715116"]
    assert healed["team2_name"] == "Shopify Rebellion GC"
    assert healed["p_model"] == 0.5 and healed["model_version"] == "vt"
