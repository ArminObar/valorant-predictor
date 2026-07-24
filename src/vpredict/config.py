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
CRAWL_FLUSH_MATCHES = 250       # persist parsed matches to the store this often

# --------------------------------------------------------------------------- leakage guard
# We only know a match's START time from vlr.gg. To guarantee that a feature for
# match M never uses a match that had not FINISHED when M started, a prior match
# is only eligible if start + assumed_duration(best_of) <= M.start.
ASSUMED_DURATION_HOURS = {1: 1.5, 3: 3.0, 5: 5.0}
DEFAULT_DURATION_HOURS = 3.0

# --------------------------------------------------------------------------- feature engine defaults
HALF_LIFE_GRID_DAYS = [30, 60, 90, 180, 365]
ROSTER_FACTOR_GRID = [0.5, 0.8, 1.0]      # per-changed-player weight multiplier; 1.0 = off
DEFAULT_HALF_LIFE_DAYS = 90
DEFAULT_ROSTER_FACTOR = 0.8
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
