"""Central configuration. Every tunable lives here so runs are reproducible."""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- paths
ROOT = Path(os.environ.get("VPREDICT_ROOT", Path(__file__).resolve().parents[2]))
DATA_DIR = Path(os.environ.get("VPREDICT_DATA", ROOT / "data"))
# Measurement workspaces (`memharness.py growth`) re-root ALL data paths —
# store, models bundle, ledger — at $VPREDICT_WORKSPACE/data. Deliberately
# takes precedence over VPREDICT_DATA so a lingering deploy env var can never
# aim a size-limited retrain at the real bundle or freeze garbage predictions
# into the real ledger. Never set in production.
_ws = os.environ.get("VPREDICT_WORKSPACE")
if _ws:
    DATA_DIR = Path(_ws) / "data"
CACHE_DIR = DATA_DIR / "cache"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = DATA_DIR / "models"
REPORTS_DIR = DATA_DIR / "reports"
LEDGER_PATH = DATA_DIR / "serving" / "ledger.sqlite"

for _d in (CACHE_DIR, RAW_DIR, PROCESSED_DIR, MODELS_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

MATCHES_JSONL = RAW_DIR / "matches.jsonl"
UPCOMING_JSONL = RAW_DIR / "upcoming.jsonl"

# --------------------------------------------------------------------------- scraping
VLR_BASE = "https://www.vlr.gg"
USER_AGENT = (
    "valorant-predictor/0.1 (student research project; polite single-thread scraper; "
    "cached; contact via repo issues)"
)
MIN_REQUEST_INTERVAL_S = 1.1   # >= 1s between requests, hard floor enforced in code
UPCOMING_CACHE_TTL_S = 15 * 60  # listing pages for upcoming matches go stale fast
# Keys a listing uses for unresolved bracket slots. A frozen row carrying
# one of these is awaiting resolution; the key is NOT a team identity, so
# name mapping treats it as adoptable, never as a mismatch (§57).
PLACEHOLDER_TEAM_KEYS = {"tbd", "tba"}
CRAWL_FLUSH_MATCHES = 250       # persist parsed matches to the store this often

# --------------------------------------------------------------------------- leakage guard
# We only know a match's START time from vlr.gg. To guarantee that a feature for
# match M never uses a match that had not FINISHED when M started, a prior match
# is only eligible if start + assumed_duration(best_of) <= M.start.
ASSUMED_DURATION_HOURS = {1: 1.5, 3: 3.0, 5: 5.0}
# Healing pass (LOG entry 41): a stored match still upcoming/live this long
# after start + assumed duration is presumed trapped by a pre-completion
# cached body and gets one forced refetch per refresh cycle. Lookback bounds
# how long a cancelled fixture keeps consuming one request per cycle.
HEAL_SLACK_HOURS = 2.0
HEAL_LOOKBACK_DAYS = 14
DEFAULT_DURATION_HOURS = 3.0

# --------------------------------------------------------------------------- feature engine defaults
HALF_LIFE_GRID_DAYS = [30, 60, 90, 180, 365]
ROSTER_FACTOR_GRID = [0.5, 0.8, 1.0]      # per-changed-player weight multiplier; 1.0 = off
DEFAULT_HALF_LIFE_DAYS = 90
DEFAULT_ROSTER_FACTOR = 0.8
# Calibrated probabilities are clipped to [CAL_OUTPUT_CLIP, 1 - CAL_OUTPUT_CLIP]
# at transform time. Provenance (LOG entries 31-32): a healthy Platt fit on
# ~800 validation rows spans ~[0.005, 0.995] on its own; a SATURATED
# calibrator (isotonic freshly past its admission gate, or Platt on a tiny
# separable slice) otherwise claims 0/1 exactly, which 4-decimal rounding
# then publishes as certainty. The clip bounds any calibrator's claims at
# what a healthy fit could evidence. Chosen by judgment from the r41
# measurement, not tuned.
CAL_OUTPUT_CLIP = 0.005
# Bumped on ANY model-definition change (prediction behavior, feature set,
# calibration) — the convention broadened after LOG entry 36: the version
# hash makes such changes VISIBLE, and the refresh cycle now also ACTS on
# this number, retraining exactly once when a deploy carries a rev the
# serving bundle predates (same converge-once pattern as LOG entry 26).
# rev 2 = calibrated-output clip + publish clamp (LOG entry 32);
# rev 3 = stand-in features (§19) + deploy-retrain trigger (LOG entry 36);
# rev 4 = smooth-isotonic calibration candidate in the menu (§21 option B,
#         LOG entry 37) — output shape can change if it wins selection.
BUNDLE_BEHAVIOR_REV = 5
# Published probabilities (ledger, upcoming JSON, backtest rows) are rounded
# to this many decimals and then clamped inside (0, 1) by one ulp of that
# rounding — a probability of exactly 0.0000 or 1.0000 is an evidentially
# indefensible claim and breaks log-loss accounting.
PROB_DECIMALS = 4
# Public-API rate limit, per client IP, sliding 60 s window. 0
# disables. Env override VPREDICT_RATE_LIMIT_PER_MIN for ops tuning
# without a deploy. Sized for humans and honest dashboards, not
# scrapers: the heaviest endpoint costs ~1 s warm.
RATE_LIMIT_PER_MIN = int(os.environ.get(
    "VPREDICT_RATE_LIMIT_PER_MIN", "120"))
# Match-detail rating chart: points per team (last N completed
# matches before the predicted match's start; same eligibility rule
# as every other as-of surface). Display context only.
RATING_TRAJECTORY_N = 10

SHRINK_M_ROUNDS = 60        # pseudo-rounds pulled toward league mean for round-rate stats
SHRINK_M_PISTOLS = 16       # pseudo-pistol-rounds (~8 maps) for pistol win rate
MIN_MAPS_FOR_MAP_ELO = 8    # below this, per-map Elo is blended toward overall Elo
MAP_ELO_BLEND_M = 10.0      # blend weight: w = n_map / (n_map + M)

# --------------------------------------------------------------------------- Elo
ELO_BASE = 1500.0
ELO_SCALE = 400.0
ELO_K_GRID = [16, 24, 32, 40, 50, 64, 80, 100, 128]
DEFAULT_ELO_K = 32

# --------------------------------------------------------------------------- modeling
# Sample-size gates from the build spec, measured on usable MATCHES after cleaning.
GATE_SIMPLE_MAX = 500       # < 500 matches: logistic regression / Elo only
GATE_GBM_MAX = 3000         # 500..3000: + gradient boosting; >3000: same menu, no NNs
TRAIN_FRACTION = 0.70
VAL_FRACTION = 0.15         # remainder is test
RANDOM_SEED = 7
MIN_MAPS_HISTORY = 3        # a team needs >=3 prior eligible maps or the row is dropped
LEAKAGE_SPOT_CHECKS = 12    # random rows re-verified with truncated history at build time

# --------------------------------------------------------------------------- serving
LEDGER_FREEZE_MARGIN_S = 300  # predictions must be logged >= 5 min before match start
CURRENT_POOL_WINDOW_DAYS = 60
CURRENT_POOL_SIZE = 7
# Recency half-life for pool MEMBERSHIP (ASSUMPTIONS §36): each in-window
# play is weighted 0.5 ** (age_days / half_life) so map rotations phase in
# within weeks instead of a full window length. None or <= 0 restores raw
# counts. Averaging across the chosen pool remains uniform (§8).
CURRENT_POOL_HALF_LIFE_DAYS = 14.0

# --------------------------------------------------------------------------- hand weights
# The original 13 hand-designed metrics from the project brief. The brief did not
# include the numeric weights that were hand-assigned to them, so the comparison
# chart defaults to uniform weights. Paste real weights here to make the chart
# reflect them (they are only used for that chart, never for prediction).
HAND_WEIGHTS: dict[str, float] = {
    "map_win_rate": 1.0,
    "first_kill_diff_per_12": 1.0,
    "pistol_win_pct": 1.0,
    "bonus_conversion_pct": 1.0,
    "anti_bonus_win_pct": 1.0,
    "post_plant_win_pct": 1.0,
    "opener_conversion_pct": 1.0,
    "clutch_pct": 1.0,
    "multikill_round_pct": 1.0,
    "economy_stability_index": 1.0,
    "attack_side_efficiency": 1.0,
    "defense_side_efficiency": 1.0,
    "league_normalized_versions": 1.0,
}

# Mapping from implemented model features to the closest original hand metric,
# used only by the importance-vs-hand-weights chart.
FEATURE_TO_HAND_METRIC = {
    "round_share_diff": "map_win_rate",
    "atk_eff_diff": "attack_side_efficiency",
    "def_eff_diff": "defense_side_efficiency",
    "fk_diff12_diff": "first_kill_diff_per_12",
    "pistol_wr_diff": "pistol_win_pct",
    "clutch_per_map_diff": "clutch_pct",
    "multikill_per_map_diff": "multikill_round_pct",
    "fullbuy_wr_diff": "economy_stability_index",
    "lowbuy_wr_diff": "economy_stability_index",
}

# --- serving refresh policy -------------------------------------------------
RETRAIN_MAX_AGE_DAYS = 7      # retrain at least weekly
RETRAIN_NEW_MATCHES = 100     # ...or when this many new matches arrived
# Scheduled top-up crawl window (judgment constants, untuned — see LOG entry 20).
# The top-up's `since` is anchored to the newest COMPLETED match in the store,
# minus an overlap margin: listings are newest-first, but entries occasionally
# appear slightly out of order, and the margin also self-heals arbitrary
# outage gaps. On an EMPTY store there is nothing to anchor to; bound that
# first crawl to a fixed bootstrap window (deepening history further is
# backfill_results's job, not the scheduler's).
TOPUP_OVERLAP_DAYS = 3
TOPUP_BOOTSTRAP_DAYS = 30

# --------------------------------------------------------------------------- odds capture (runs on the owner's Mac, never on Render)
ODDS_DIR = DATA_DIR / "odds"
ODDS_JSONL = ODDS_DIR / "odds.jsonl"          # append-only capture log
ODDS_RAW_DIR = ODDS_DIR / "raw"               # append-only raw API responses
ODDS_ALIASES_JSON = ODDS_DIR / "aliases.json" # book-name -> vlr-name overrides
ODDS_UPCOMING_URL = "https://vpredict.onrender.com/api/upcoming"
ODDS_CLOSE_WINDOW_MIN = 20    # a capture within this window of start_ts is the "close"
ODDS_LINK_MAX_START_DELTA_H = 6   # name-matched fixture must also start within
                                  # this many hours of the prediction, or the
                                  # link is refused (LOG entry 61)
ODDS_MIN_INTERVAL_S = 1.0     # politeness floor between odds-source requests
CLOUDBET_BASE_URL = "https://sports-api.cloudbet.com/pub/v2/odds"
# Headline column: first source in this list that priced the match wins.
# Pinnacle first: sharpest widely-referenced book, the standard CLV yardstick.
# All captured books are stored; nothing is ever averaged.
ODDS_BOOK_PRIORITY = ["pinnacle", "cloudbet"]
VPREDICT_BASE_URL = "https://vpredict.onrender.com"   # push target for the Mac leg
# --push re-sends every local record inside this window (not just this run's
# appends): a failed push self-heals on the next fire because the server
# ingest dedupes by full record identity (ASSUMPTIONS §46).
ODDS_PUSH_WINDOW_H = 24

# --------------------------------------------------------------------------- markets & EV (analysis time)
# Pre-registered BEFORE any graded market-covered pick existed (§13 spec item
# 5, recorded 2026-07-24): EV aggregates stay "unvalidated" in the UI until
# this many market-covered picks have graded. Changing it after grading
# starts would be moving the goalposts — don't.
# Maps-total picks are excluded from EV/CLV aggregates and from the EV
# validation gate: the frozen maps distribution assumes independent maps,
# and measured reality (LOG 34 context / ASSUMPTIONS §20) puts P(2-0) at
# 60.7% vs the assumption's 53.5% — a known ~7-point bias that would ship
# phantom value on overs. Owner-directed 2026-07-24. Flip to False only
# with the correlation fix, which is a versioned model change with a
# labeled backtest re-run.
EV_EXCLUDE_TOTALS = True

EV_MIN_GRADED_PICKS = 100
# Earliest moment a markets.json could have been publicly served: the
# commit that created odds/markets.py and the /api/markets route
# (0d2ddf2, authored 2026-07-25T06:20:25Z). Picks whose ENTRY precedes
# this cannot have been public pre-match, so they are labeled and kept
# out of the validation gate and EV aggregates (ASSUMPTIONS §69).
# Reversible by design: relaxing this constant re-admits them; the
# per-pick label ships either way.
MARKETS_PUBLIC_SINCE = "2026-07-25T06:20:25+00:00"
# Series-grain probabilities outside the test window's supported range are
# labeled EXTRAPOLATION, not edge, and excluded from EV aggregates. Band ≈
# the frozen test window's series-probability range (results §2).
EV_EXTRAPOLATION_LO = 0.15
EV_EXTRAPOLATION_HI = 0.88
MARKETS_JSON = PROCESSED_DIR / "markets.json"

# Phase-1 Trends (ASSUMPTIONS §61): store-derived team form windows.
TRENDS_JSON = PROCESSED_DIR / "trends.json"
TRENDS_WINDOW_MAPS = 10       # per-team rolling window
TRENDS_ACTIVE_DAYS = 60       # hide teams with no completed map since
TRENDS_MIN_LIFETIME_MAPS = 5  # below this a window is noise
TRENDS_ROWS_JSON = PROCESSED_DIR / "trends_rows.json"
TRENDS_SCOPE_MIN_MAPS = 5     # min maps INSIDE a custom scope to list a team

# Roster-continuity feature family, Phase 1 (ASSUMPTIONS §66). Membership
# only, no performance stats, no new scraping. Default reflects the
# pre-registered ablation verdict recorded in §66; serving auto-detects
# from the bundle's feature_names, so this flag only steers TRAINING.
ROSTER_CONTINUITY_FEATURES = True   # §66 ablation verdict: SHIP

# Hypothetical unit tracker (ASSUMPTIONS §59). Imaginary units on a FIXED,
# non-compounding notional: a sizing diagnostic, never money, never a
# bankroll simulation. Quarter Kelly with the sizing EV clipped and the
# stake hard-capped so no single outlier EV can dominate the aggregate.
# Only picks whose match starts on/after the start boundary count: entry
# prices frozen before the LOG-59 capture fix may be close-reused, and a
# tracker seeded on possibly-phantom entries would be unfalsifiable.
UNIT_TRACKER_START_TS = "2026-08-08T00:00:00+00:00"
UNIT_TRACKER_NOTIONAL_UNITS = 100.0
UNIT_TRACKER_KELLY_FRACTION = 0.25
UNIT_TRACKER_EV_CLIP = 0.10          # sizing uses min(EV, 10%)
UNIT_TRACKER_STAKE_CAP_UNITS = 3.0   # hard per-pick ceiling
