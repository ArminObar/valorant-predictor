#!/usr/bin/env python3
"""Generate a seeded, loudly watermarked SYNTHETIC dataset so the full
pipeline (evaluate -> train -> predict -> serve) is demoable with zero
network access. Every record carries synthetic=true and is watermarked in
every downstream report and bundle. Numbers from this data say nothing about
real Valorant."""
import argparse
import math
import random
from datetime import datetime, timedelta, timezone

from vpredict import config
from vpredict.data import store
from vpredict.data.schema import Match, MapResult, PlayerMapStats, RoundResult

MAPS = ["Ascent", "Bind", "Breeze", "Fracture", "Haven", "Lotus", "Pearl", "Split"]


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _rounds(rng, s1: int, s2: int) -> list[RoundResult]:
    """A plausible round sequence hitting the final score, halves at 12."""
    seq = ["team1"] * s1 + ["team2"] * s2
    rng.shuffle(seq)
    out = []
    for i, w in enumerate(seq, start=1):
        attacking = "team1" if (i <= 12) else "team2"       # team1 attacks 1st half
        side = "attack" if w == attacking else "defense"
        out.append(RoundResult(number=i, winner=w, side=side,
                               win_method=rng.choice(["elim", "boom", "defuse", "time"])))
    return out


def _players(rng, roster, fk_edge: float) -> list[PlayerMapStats]:
    return [PlayerMapStats(name=n, agent="", acs=rng.uniform(140, 280),
                           kills=rng.randint(8, 25), deaths=rng.randint(8, 22),
                           assists=rng.randint(2, 12),
                           fk=max(0, round(rng.gauss(1.6 + fk_edge, 1.0))),
                           fd=max(0, round(rng.gauss(1.6 - fk_edge, 1.0))))
            for n in roster]


def gen(n_matches: int, seed: int, start: datetime) -> list[Match]:
    rng = random.Random(seed)
    teams = [f"Team {chr(65+i)}{chr(65+j)}" for i in range(6) for j in range(5)][:30]
    strength = {t: rng.gauss(0, 1.0) for t in teams}
    skew = {t: {m: rng.gauss(0, 0.35) for m in MAPS} for t in teams}
    rosters = {t: [f"{t.lower().replace(' ', '')}_p{j}" for j in range(1, 6)]
               for t in teams}
    out: list[Match] = []
    t = start
    for i in range(n_matches):
        t += timedelta(minutes=rng.randint(45, 240))
        a, b = rng.sample(teams, 2)
        if rng.random() < 0.02:
            rosters[a] = rosters[a][:4] + [f"{a.lower().replace(' ', '')}_p{rng.randint(6, 99)}"]
        best_of = 5 if rng.random() < 0.08 else 3
        pool = rng.sample(MAPS, 7)
        picks, remains = pool[:best_of - 1], pool[best_of - 1]
        veto = "; ".join([f"{a} ban {pool[5]}", f"{b} ban {pool[6]}"] +
                         [f"{[a, b][j % 2]} pick {m}" for j, m in enumerate(picks)] +
                         [f"{remains} remains"])
        need, wa, wb = best_of // 2 + 1, 0, 0
        maps: list[MapResult] = []
        for idx, mname in enumerate(picks + [remains], start=1):
            if wa == need or wb == need:
                break
            edge = (strength[a] - strength[b] + skew[a][mname] - skew[b][mname])
            a_wins = rng.random() < _sig(1.1 * edge)
            lo = rng.randint(2, 11)
            s1, s2 = (13, lo) if a_wins else (lo, 13)
            rounds = _rounds(rng, s1, s2)
            # regulation side splits consistent with the round list
            t1_atk = sum(1 for r in rounds if r.number <= 12 and r.winner == "team1")
            t2_atk = sum(1 for r in rounds if r.number > 12 and r.winner == "team2")
            maps.append(MapResult(
                game_id=f"g{i:05d}{idx}", map_name=mname, index=idx,
                team1_score=s1, team2_score=s2,
                team1_ct=s1 - t1_atk, team1_t=t1_atk,
                team2_ct=s2 - t2_atk, team2_t=t2_atk,
                rounds=rounds,
                team1_players=_players(rng, rosters[a], 0.4 * edge),
                team2_players=_players(rng, rosters[b], -0.4 * edge)))
            wa, wb = wa + int(a_wins), wb + int(not a_wins)
        out.append(Match(
            match_id=f"syn{i:05d}", url=f"synthetic://{i}", start_ts=t.replace(tzinfo=timezone.utc),
            status="completed", best_of=best_of,
            event=f"Synthetic Cup {'Playoffs' if rng.random() < 0.2 else 'Group Stage'}",
            series="Week 1", team1_name=a, team2_name=b,
            team1_maps=wa, team2_maps=wb,
            winner="team1" if wa > wb else "team2",
            veto_raw=veto, maps=maps, synthetic=True))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed", type=int, default=config.RANDOM_SEED)
    ap.add_argument("--out", default=str(config.DATA_DIR / "demo" / "matches.jsonl"))
    args = ap.parse_args()
    from pathlib import Path
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    matches = gen(args.n, args.seed,
                  datetime.now(timezone.utc) - timedelta(days=150))
    store.upsert_matches(matches, Path(args.out))
    print("=" * 60 + "\n  SYNTHETIC DEMO DATA — watermarked end to end\n" + "=" * 60)
    print(f"wrote {len(matches)} matches -> {args.out}")
    print(f"next: python scripts/evaluate.py --data {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
