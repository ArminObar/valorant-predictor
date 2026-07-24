"""Model selection, calibration, and bundle persistence — shared by
scripts/evaluate.py (reporting) and scripts/train.py (serving), so the model
that goes live is selected by the identical procedure that was evaluated.

Gate (from the build spec, on usable matches): < 500 -> regularized logistic
regression only; 500-3000 -> + heavily regularized LightGBM; > 3000 -> same
menu, no neural networks. Selection by validation log loss; calibration on
validation (Platt always, isotonic only when validation is large enough).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .. import config

EPS = 1e-6
LR_C_GRID = [0.03, 0.1, 0.3, 1.0, 3.0]
ISOTONIC_MIN_VAL = 800


def _clip(p: np.ndarray) -> np.ndarray:
    return np.clip(p, EPS, 1 - EPS)


def ll(y, p) -> float:
    return float(log_loss(y, _clip(np.asarray(p, dtype=float)), labels=[0, 1]))


# --------------------------------------------------------------------------- calibrators
class PlattCalibrator:
    """Logistic regression on the logit of the raw probability. Picklable."""

    name = "platt"

    def fit(self, p_val: np.ndarray, y_val: np.ndarray) -> "PlattCalibrator":
        z = np.log(_clip(p_val) / (1 - _clip(p_val))).reshape(-1, 1)
        self._lr = LogisticRegression(C=1e6, max_iter=2000).fit(z, y_val)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        z = np.log(_clip(p) / (1 - _clip(p))).reshape(-1, 1)
        return self._lr.predict_proba(z)[:, 1]


class IsotonicCalibrator:
    name = "isotonic"

    def fit(self, p_val: np.ndarray, y_val: np.ndarray) -> "IsotonicCalibrator":
        self._iso = IsotonicRegression(out_of_bounds="clip").fit(p_val, y_val)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return _clip(self._iso.predict(p))


def fit_calibrator(p_val: np.ndarray, y_val: np.ndarray):
    cands = [PlattCalibrator().fit(p_val, y_val)]
    if len(y_val) >= ISOTONIC_MIN_VAL:
        cands.append(IsotonicCalibrator().fit(p_val, y_val))
    best = min(cands, key=lambda c: ll(y_val, c.transform(p_val)))
    return best.name, best


# --------------------------------------------------------------------------- candidates
def fit_lr(X_tr, y_tr, X_val, y_val) -> dict:
    best = (None, np.inf, None)
    for C in LR_C_GRID:
        pipe = make_pipeline(StandardScaler(),
                             LogisticRegression(C=C, max_iter=4000))
        pipe.fit(X_tr, y_tr)
        v = ll(y_val, pipe.predict_proba(X_val)[:, 1])
        if v < best[1]:
            best = (pipe, v, C)
    return {"name": f"logistic_regression(C={best[2]})", "model": best[0],
            "val_ll": best[1]}


def fit_lgbm(X_tr, y_tr, X_val, y_val) -> dict | None:
    try:
        import lightgbm as lgb
    except ImportError:
        return None
    model = lgb.LGBMClassifier(
        n_estimators=600, learning_rate=0.03, num_leaves=15,
        min_child_samples=40, feature_fraction=0.8, subsample=0.9,
        subsample_freq=1, reg_alpha=1.0, reg_lambda=5.0,
        random_state=config.RANDOM_SEED, verbose=-1,
    )
    cb = [lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)]
    try:  # lightgbm >= 4.7
        model.fit(X_tr, y_tr, eval_X=X_val, eval_y=np.asarray(y_val),
                  eval_metric="binary_logloss", callbacks=cb)
    except TypeError:  # older lightgbm: eval_set API
        model.fit(X_tr, y_tr, eval_set=[(X_val, np.asarray(y_val))],
                  eval_metric="binary_logloss", callbacks=cb)
    return {"name": f"lightgbm(best_iter={model.best_iteration_})",
            "model": model,
            "val_ll": ll(y_val, model.predict_proba(X_val)[:, 1])}


def select_model(X_tr, y_tr, X_val, y_val, n_train_matches: int) -> dict:
    """Fit the gated menu, pick by validation log loss, calibrate on val.
    Returns {model, calibrator, cal_name, name, gate_note, val_ll}."""
    cands = [fit_lr(X_tr, y_tr, X_val, y_val)]
    gate_note = f"{n_train_matches} usable matches -> logistic regression"
    if n_train_matches >= config.GATE_SIMPLE_MAX:
        g = fit_lgbm(X_tr, y_tr, X_val, y_val)
        if g:
            cands.append(g)
            gate_note += " + regularized LightGBM"
    chosen = min(cands, key=lambda c: c["val_ll"])
    p_val = chosen["model"].predict_proba(X_val)[:, 1]
    cal_name, cal = fit_calibrator(p_val, np.asarray(y_val))
    return {"model": chosen["model"], "calibrator": cal, "cal_name": cal_name,
            "name": chosen["name"], "gate_note": gate_note,
            "val_ll": chosen["val_ll"]}


def predict_calibrated(sel: dict, X) -> np.ndarray:
    return sel["calibrator"].transform(sel["model"].predict_proba(X)[:, 1])


# --------------------------------------------------------------------------- bundle
def make_version(params: dict) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    h = hashlib.sha1(json.dumps(params, sort_keys=True, default=str)
                     .encode()).hexdigest()[:8]
    return f"{stamp}-{h}"


def save_bundle(sel: dict, feature_names: list[str], params: dict,
                extra: dict, path=None) -> str:
    path = path or (config.MODELS_DIR / "model.joblib")
    bundle = {
        "model": sel["model"], "calibrator": sel["calibrator"],
        "model_name": sel["name"], "cal_name": sel["cal_name"],
        "feature_names": feature_names, "params": params,
        "version": make_version({**params, "model": sel["name"]}),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    joblib.dump(bundle, path)
    return str(path)


def load_bundle(path=None) -> dict:
    return joblib.load(path or (config.MODELS_DIR / "model.joblib"))


# --------------------------------------------------------------------------- end-to-end training
def train_and_save(data_path=None, half_life_days: float | None = None,
                   roster_factor: float | None = None, bundle_path=None) -> dict:
    """Fit the exact evaluated pipeline (train -> select on val -> calibrate on
    val) and persist the bundle scripts/predict_upcoming.py serves from. The
    Elo baseline K is tuned here too and stored so the ledger's comparison
    column uses the same baseline the report did."""
    from ..data import store as _store
    from ..features.build import augment_swapped, build_features, chronological_split
    from ..memprof import phase
    from .baselines import matches_lite_from_maps, tune_elo_k

    with phase("load_store"):
        matches = _store.load_matches(data_path or config.MATCHES_JSONL)
        maps_df = _store.maps_frame(matches)
    if maps_df.empty:
        raise ValueError("no completed matches — scrape before training")
    with phase("build_features"):
        fs = build_features(
            maps_df,
            half_life_days=half_life_days or config.DEFAULT_HALF_LIFE_DAYS,
            roster_factor=roster_factor or config.DEFAULT_ROSTER_FACTOR)
    splits = chronological_split(fs.meta)
    tr, va = splits["train"], splits["val"]
    y = fs.y.to_numpy()
    n_train = int(fs.meta.loc[tr, "match_id"].nunique())
    with phase("select_calibrate"):
        X_tr, y_tr = augment_swapped(fs.X[tr], fs.y[tr])
        sel = select_model(X_tr, y_tr, fs.X[va], y[va], n_train)
    best_k, _, _ = tune_elo_k(matches_lite_from_maps(maps_df), fs.meta, y, va)
    synthetic = bool(fs.meta["synthetic"].any())
    path = save_bundle(
        sel, fs.feature_names, fs.params,
        extra={"elo_k_baseline": float(best_k),
               "n_matches": int(fs.meta["match_id"].nunique()),
               "data_max_ts": str(fs.meta["start_ts"].max()),
               "synthetic_data": synthetic},
        path=bundle_path)
    return {"path": path, "model": sel["name"], "calibrator": sel["cal_name"],
            "val_ll": sel["val_ll"], "elo_k_baseline": best_k,
            "synthetic": synthetic}
