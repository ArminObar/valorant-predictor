"""Display-consistency regressions from the cross-page audit (LOG 52-54).

Three properties the audit either proved or hardened:
- /api/model reads the bundle from disk on every request, so a server-side
  retrain shows up on the very next request with no restart. There was no
  caching bug to fix; this pins the behavior so one can never be added.
- The scoreboard's pending list, when it must truncate, drops the far
  future — never the next matches to play (the old DESC/100 pair dropped
  exactly the soonest once pending passed the cap).
- Published listing names are mapped onto the frozen row's team order by
  key, so a listing that swaps display order can never caption the frozen
  probability with the wrong team.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import joblib
from fastapi.testclient import TestClient

from vpredict.modeling.predict import _names_for_row
from vpredict.serving.api import create_app
from vpredict.serving.ledger import Ledger


def test_model_endpoint_reflects_bundle_swap_without_restart(tmp_path):
    """Retrain-while-serving: the summary must reflect the live bundle on
    the next request, never a value cached at startup."""
    bundle = tmp_path / "models" / "model.joblib"
    bundle.parent.mkdir(parents=True)
    joblib.dump({"version": "vA", "model_name": "lr", "model": object(),
                 "calibrator": object()}, bundle)
    c = TestClient(create_app(data_dir=tmp_path))
    assert c.get("/api/model").json()["version"] == "vA"
    assert c.get("/api/health").json()["model_version"] == "vA"

    # The in-process refresh loop overwrites the same path on retrain.
    joblib.dump({"version": "vB", "model_name": "lr", "model": object(),
                 "calibrator": object()}, bundle)
    assert c.get("/api/model").json()["version"] == "vB"
    assert c.get("/api/health").json()["model_version"] == "vB"
    # fitted objects never leave the server
    assert "model" not in c.get("/api/model").json()


def test_scoreboard_pending_keeps_the_soonest(tmp_path):
    """505 pending rows against the 500 cap: the response holds the 500
    soonest, soonest first; only the far future is cut."""
    now = datetime.now(timezone.utc)
    led = Ledger(tmp_path / "serving" / "ledger.sqlite")
    for i in range(505):
        led.insert_prediction(
            match_id=f"m{i:04d}", start_ts=now + timedelta(hours=1, minutes=i),
            team1=f"a{i}", team2=f"b{i}", team1_name="A", team2_name="B",
            event="E", best_of=3, p_model=0.6, p_elo=0.55,
            model_version="vt", now=now)
    led.close()

    sb = TestClient(create_app(data_dir=tmp_path)).get("/api/scoreboard").json()
    assert sb["summary"]["n_pending"] == 505      # counts are never capped
    pend = sb["pending"]
    assert len(pend) == 500
    starts = [r["start_ts"] for r in pend]
    assert starts == sorted(starts)               # soonest first
    assert pend[0]["match_id"] == "m0000"         # the next match to play
    # the five cut rows are exactly the furthest out
    assert {f"m{i:04d}" for i in range(500, 505)} == (
        {f"m{i:04d}" for i in range(505)} - {r["match_id"] for r in pend})


class _Listing:
    """Duck-typed stand-in for a Match: key_team + display names."""

    def __init__(self, k1, k2, n1, n2):
        self._k = {"team1": k1, "team2": k2}
        self.team1_name, self.team2_name = n1, n2

    def key_team(self, which):
        return self._k[which]


def test_published_names_follow_frozen_key_order():
    row = {"team1": "111", "team2": "222",
           "team1_name": "Frozen One", "team2_name": "Frozen Two"}
    # listing agrees with the frozen order
    assert _names_for_row(row, _Listing("111", "222", "New One", "New Two")) \
        == ("New One", "New Two", "aligned")
    # listing swapped display order after the freeze: names swap with it,
    # so the frozen team1 probability still captions the frozen team1
    assert _names_for_row(row, _Listing("222", "111", "New Two", "New One")) \
        == ("New One", "New Two", "swapped")
    # listing keys no longer match the frozen row at all: keep the frozen
    # names rather than guess an orientation
    assert _names_for_row(row, _Listing("333", "444", "X", "Y")) \
        == ("Frozen One", "Frozen Two", "unmatched")
