"""Parser regression tests.

The map-name case is a field-found bug from the first live scrape: vlr.gg nests
the veto label inside the map-name span (`<span>Lotus<span>PICK</span></span>`),
so naive get_text() yields "LotusPICK" while decider maps yield "Lotus" — the
same map fragments into two keys and silently halves per-map sample sizes.
These tests drive the FULL match-page parser over hand-built HTML that mirrors
the real structure (nothing copied from third-party fixtures).
"""
from __future__ import annotations

import pytest

from vpredict.scraping.parse_match import parse_match_page


def _map_block(game_id: str, name_html: str, s1: int, s2: int) -> str:
    return f"""
    <div class="vm-stats-game" data-game-id="{game_id}">
      <div class="vm-stats-game-header">
        <div class="team">
          <div class="score">{s1}</div>
          <span class="mod-ct">{s1 // 2}</span> / <span class="mod-t">{s1 - s1 // 2}</span>
        </div>
        <div class="map">
          <div>{name_html}</div>
          <div class="map-duration">41:03</div>
        </div>
        <div class="team mod-right">
          <div class="score">{s2}</div>
          <span class="mod-ct">{s2 // 2}</span> / <span class="mod-t">{s2 - s2 // 2}</span>
        </div>
      </div>
    </div>"""


def _page(maps_html: str) -> str:
    return f"""<html><body>
    <div class="match-header-super">
      <a href="/event/9"><div>Synthetic Masters</div></a>
      <div class="match-header-event-series">Playoffs: Grand Final</div>
    </div>
    <div class="match-header-date">
      <div class="moment-tz-convert" data-utc-ts="2026-07-20 15:00:00">Jul 20</div>
    </div>
    <a class="match-header-link mod-1" href="/team/11/red">
      <div class="match-header-link-name mod-1"><div class="wf-title-med">Red Team</div></div>
    </a>
    <a class="match-header-link mod-2" href="/team/22/blu">
      <div class="match-header-link-name mod-2"><div class="wf-title-med">Blue Team</div></div>
    </a>
    <div class="match-header-vs-score">
      <span class="match-header-vs-score-winner">2</span><span>:</span><span>1</span>
    </div>
    <div class="match-header-vs-note">Final</div>
    <div class="match-header-vs-note">Bo3</div>
    {maps_html}
    </body></html>"""


def test_map_names_never_include_veto_labels():
    """Regression: picked maps carried the nested PICK label; deciders did not.
    All three maps of a series must come out under clean, consistent keys."""
    maps_html = (
        _map_block("101", '<span>Lotus<span class="picked mod-1">PICK</span></span>', 13, 7)
        + _map_block("102", '<span>Ascent<span class="picked mod-2">PICK</span></span>', 9, 13)
        + _map_block("103", "<span>Breeze</span>", 13, 11)   # decider: no label
    )
    m = parse_match_page(_page(maps_html), "77001", "https://example.test/77001")
    assert [mp.map_name for mp in m.maps] == ["Lotus", "Ascent", "Breeze"]
    assert m.status == "completed" and m.winner == "team1" and m.best_of == 3
    assert (m.maps[0].team1_score, m.maps[0].team2_score) == (13, 7)


def test_same_map_picked_and_decider_share_one_key():
    """The exact fragmentation failure: Lotus as a pick and Lotus as a decider
    must be stored under one key."""
    maps_html = (
        _map_block("201", '<span>Lotus<span class="picked mod-1">PICK</span></span>', 13, 5)
        + _map_block("202", "<span>Lotus</span>", 13, 10)
    )
    m = parse_match_page(_page(maps_html), "77002", "")
    names = {mp.map_name for mp in m.maps}
    assert names == {"Lotus"}, f"fragmented keys: {names}"


@pytest.mark.parametrize("label", ["PICK", "BAN", "DECIDER"])
def test_sibling_label_and_duration_spans_are_skipped(label):
    """Labels as sibling spans (and a duration span inside .map) must also be
    skipped, and an uppercase label glued on by any future layout change is
    stripped defensively."""
    name_html = f'<span class="picked">{label}</span><span>Sunset</span><span>41:03</span>'
    m = parse_match_page(_page(_map_block("301", name_html, 13, 4)), "77003", "")
    assert m.maps[0].map_name == "Sunset"
