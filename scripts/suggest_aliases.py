#!/usr/bin/env python3
"""Propose aliases for UNLINKED odds fixtures; write confirmed pairs.

    python scripts/suggest_aliases.py                  # interactive confirm
    python scripts/suggest_aliases.py --dry-run        # just show proposals
    python scripts/suggest_aliases.py --yes            # auto-accept >= 0.90,
                                                       #   unambiguous only
    python scripts/suggest_aliases.py --from-file data/processed/upcoming_predictions.json

Reads unlinked captures from the append-only odds log (match_id null),
dedupes by (source, home, away), scores each against the current frozen
predictions with vpredict.odds.fuzzy, and asks. Confirmed pairs are merged
into data/odds/aliases.json (book name -> vlr name, raw strings; the linker
normalizes at lookup). Identity pairs that already normalize-equal are
skipped — they need no alias.

After writing, re-run `python scripts/capture_odds.py --once`: the freeze
captures for newly-linkable fixtures append on that pass (the earlier
unlinked rows stay in the log — it is append-only — as the record that the
first sighting could not be linked).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vpredict import config
from vpredict.odds.fuzzy import suggest
from vpredict.odds.schema import iter_captures, load_aliases, normalize_team


def load_predictions(from_file: str | None) -> list[dict]:
    if from_file:
        payload = json.loads(Path(from_file).read_text(encoding="utf-8"))
    else:
        import requests
        r = requests.get(config.ODDS_UPCOMING_URL, timeout=20)
        r.raise_for_status()
        payload = r.json()
    return payload.get("predictions", [])


def unlinked_fixtures() -> list[dict]:
    """Latest sighting per (source, home, away) among unlinked captures."""
    seen: dict[tuple, dict] = {}
    for c in iter_captures():
        if c.match_id is not None:
            continue
        key = (c.source, c.book_home, c.book_away)
        seen[key] = {"source": c.source, "book_home": c.book_home,
                     "book_away": c.book_away, "captured_at": c.captured_at}
    return sorted(seen.values(), key=lambda d: d["captured_at"], reverse=True)


def _merge_aliases(new_pairs: dict[str, str]) -> int:
    path = config.ODDS_ALIASES_JSON
    current = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    added = 0
    for book, vlr in new_pairs.items():
        if normalize_team(book) == normalize_team(vlr):
            continue                       # exact linker already handles it
        if current.get(book) != vlr:
            current[book] = vlr
            added += 1
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=1, sort_keys=True,
                                   ensure_ascii=False), encoding="utf-8")
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-file", default=None,
                    help="read predictions from a local JSON instead of the "
                         "live API")
    ap.add_argument("--threshold", type=float, default=0.75)
    ap.add_argument("--dry-run", action="store_true",
                    help="show proposals, write nothing")
    ap.add_argument("--yes", action="store_true",
                    help="accept unambiguous proposals scoring >= 0.90 "
                         "without asking; everything else still asks")
    args = ap.parse_args()

    predictions = load_predictions(args.from_file)
    if not predictions:
        print("No frozen predictions available to match against.")
        return 1
    fixtures = unlinked_fixtures()
    if not fixtures:
        print("No unlinked fixtures in the odds log — nothing to do.")
        return 0
    aliases = load_aliases()

    confirmed: dict[str, str] = {}
    proposed = skipped = 0
    for fx in fixtures:
        bh, ba = fx["book_home"], fx["book_away"]
        if (aliases.get(normalize_team(bh)) and
                aliases.get(normalize_team(ba))):
            continue                       # both sides already covered
        sug = suggest(bh, ba, predictions, threshold=args.threshold)
        if sug is None:
            print(f"?  {fx['source']:9s} {bh} vs {ba} — no candidate >= "
                  f"{args.threshold:.2f}")
            skipped += 1
            continue
        p = sug.prediction
        ours = (p["team1_name"], p["team2_name"]) if sug.book_home_is_team1 \
            else (p["team2_name"], p["team1_name"])
        proposed += 1
        line = (f"{fx['source']:9s} {bh} vs {ba}  ->  "
                f"{ours[0]} vs {ours[1]}  "
                f"[{sug.team_scores[0]:.2f}/{sug.team_scores[1]:.2f}]")
        if sug.ambiguous_with is not None:
            alt = sug.ambiguous_with
            print(f"!  AMBIGUOUS: {line}")
            print(f"   close runner-up: {alt['team1_name']} vs "
                  f"{alt['team2_name']}")
            if args.dry_run:
                continue
            ans = input("   accept first pairing? [y/N] ").strip().lower()
            if ans != "y":
                skipped += 1
                continue
        elif args.dry_run:
            print(f"~  {line}")
            continue
        elif args.yes and sug.score >= 0.90:
            print(f"+  auto: {line}")
        else:
            ans = input(f"?  {line}\n   accept? [y/N/s(kip)] ").strip().lower()
            if ans != "y":
                skipped += 1
                continue
        confirmed[bh], confirmed[ba] = ours[0], ours[1]

    if args.dry_run:
        print(f"\ndry run: {proposed} proposal(s), nothing written")
        return 0
    added = _merge_aliases(confirmed)
    print(f"\n{added} alias(es) written to {config.ODDS_ALIASES_JSON} "
          f"({skipped} skipped). Now re-run: "
          f"python scripts/capture_odds.py --once")
    return 0


if __name__ == "__main__":
    sys.exit(main())
