"""Series-level aggregation: veto parsing and best-of-N win probability.

Match-level prediction is the actual deliverable; the model is trained at map
grain, so a series probability is the DP over per-map probabilities:

    P(A wins Bo-n) = sum over paths where A reaches ceil(n/2) map wins first.

For completed matches, maps that were never played (a 2-0 Bo3 has no map 3)
are recovered from the stored veto note where possible ("...; Haven remains"),
so the series probability is computed over the true post-veto map set. When
the veto is missing or unparseable, unplayed slots fall back to the mean of
the played-map probabilities — counted and reported, never silent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def series_prob(map_probs: list[float]) -> float:
    """P(team A wins a best-of-len(map_probs) series), maps independent given
    the per-map probabilities. Exact DP, no approximation."""
    n = len(map_probs)
    if n % 2 != 1:
        raise ValueError(f"best-of must be odd, got {n} map probabilities")
    need = n // 2 + 1

    def rec(i: int, a: int, b: int) -> float:
        if a == need:
            return 1.0
        if b == need:
            return 0.0
        p = map_probs[i]
        return p * rec(i + 1, a + 1, b) + (1.0 - p) * rec(i + 1, a, b + 1)

    return rec(0, 0, 0)


_PICK = re.compile(r"\bpick\s+([A-Za-z'\u2019 ]+?)\s*$", re.IGNORECASE)
_REMAINS = re.compile(r"^\s*([A-Za-z'\u2019 ]+?)\s+remains?\s*$", re.IGNORECASE)


def parse_veto(veto_raw: str, known_maps: list[str]) -> list[str] | None:
    """Parse a vlr veto note like
    'TS ban Haven; KRX ban Bind; TS pick Pearl; KRX pick Fracture; ...;
     Split remains'
    into the ordered map sequence [pick1, pick2, ..., remains].

    Returns None when nothing usable is found. Map names are canonicalised
    against `known_maps` case-insensitively; an unknown name (pool rotation)
    is kept as written rather than dropped.
    """
    if not veto_raw or not veto_raw.strip():
        return None
    canon = {m.lower(): m for m in known_maps}
    picks: list[str] = []
    remains: str | None = None
    for token in veto_raw.split(";"):
        token = token.strip()
        if not token:
            continue
        m = _REMAINS.match(token)
        if m:
            name = m.group(1).strip()
            remains = canon.get(name.lower(), name)
            continue
        m = _PICK.search(token)
        if m:
            name = m.group(1).strip()
            picks.append(canon.get(name.lower(), name))
    if not picks and remains is None:
        return None
    seq = picks + ([remains] if remains is not None else [])
    return seq or None


@dataclass
class SeriesMaps:
    """The map sequence used for a series probability, with provenance."""
    maps: list[str | None]        # None = unknown slot (mean-prob fallback)
    n_filled_from_veto: int
    n_fallback: int

    @property
    def source(self) -> str:
        if self.n_fallback:
            return "fallback"
        if self.n_filled_from_veto:
            return "veto"
        return "played"


def complete_sequence(played: list[str], veto_raw: str, best_of: int,
                      known_maps: list[str]) -> SeriesMaps:
    """Return the full best_of-length map list for a completed series.

    Played maps are always trusted for the slots that were played (in played
    order). Missing tail slots come from the parsed veto when its prefix
    agrees with what was actually played; otherwise they are None (fallback).
    """
    missing = best_of - len(played)
    if missing <= 0:
        return SeriesMaps(maps=list(played[:best_of]), n_filled_from_veto=0,
                          n_fallback=0)
    seq = parse_veto(veto_raw, known_maps)
    if seq and len(seq) == best_of:
        prefix_ok = [s.lower() for s in seq[:len(played)]] == \
                    [p.lower() for p in played]
        if prefix_ok:
            return SeriesMaps(maps=list(played) + list(seq[len(played):]),
                              n_filled_from_veto=missing, n_fallback=0)
    return SeriesMaps(maps=list(played) + [None] * missing,
                      n_filled_from_veto=0, n_fallback=missing)
