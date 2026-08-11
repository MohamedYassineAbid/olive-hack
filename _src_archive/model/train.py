"""
XGBoost trainer — Phase 2.

Trains on the combined (mock + real) dataset, saves the model to
data/artifacts/xgb_model.json, and updates calibration.json so
ml_ready flips to True.

The API picks up the new model on next startup automatically.

Usage:
    python -m src.model.train                  # uses combined dataset
    python -m src.model.train --real-only      # only real data (needs >= 90 days)
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import TimeSeriesSplit

from src.pipeline.config import DATA_ARTIFACTS, DATA_PROCESSED
from src.pipeline.features import build_features
from src.model.calibrate import calibrate, ARTIFACT_PATH

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

MODEL_PATH = DATA_ARTIFACTS / "xgb_model.json"

FEATURE_COLS = [
    "temp_max", "temp_min", "temp_range", "rh_max", "rh_mean",
    "heat_stress", "wind_max", "precip", "et0",
    "day_of_week", "month", "is_weekend",
    "reports_down_lag1", "reports_down_lag2", "reports_down_lag3",
    "reports_down_roll3", "reports_down_roll7",
    "national_reports_down", "national_reports_roll3",
]
TARGET_COL = "reports_down"


def load_dataset(real_only: bool = False) -> pd.DataFrame:
    combined = DATA_PROCESSED / "combined_dataset.parquet"
    real     = DATA_PROCESSED / "merged_dataset.parquet"

    if real_only:
        if not real.exists():
            raise FileNotFoundError("Real dataset not found — run download_data first")
        df = pd.read_parquet(real)
        log.info("Using real-only dataset (%d rows)", len(df))
    elif combined.exists():
        df = pd.read_parquet(combined)
        mock_days = df[df.get("is_mock", False) == True]["day"].nunique() if "is_mock" in df.columns else 0
        real_days = df[df.get("is_mock", False) != True]["day"].nunique() if "is_mock" in df.columns else df["day"].nunique()
        log.info("Using combined dataset (%d rows — %d mock days + %d real days)",
                 len(df), mock_days, real_days)
    else:
        raise FileNotFoundError(
            "No combined dataset found — run generate_mock_data first, "
            "or use --real-only if you have >= 90 real days"
        )
    return df


def train(real_only: bool = False) -> None:
    try:
        import xgboost as xgb
    except ImportError:
        log.error("xgboost not installed. Run: pip install 'xgboost<2.1.0'")
        raise

    df = load_dataset(real_only)
    feat = build_features(df)

    n_days = feat["day"].nunique()
    log.info("Training on %d calendar days  (%d gov-day rows)", n_days, len(feat))

    # Drop rows with NaN targets or key features
    feat = feat.dropna(subset=[TARGET_COL] + ["temp_max", "heat_stress"])
    feat = feat.fillna(0)

    # Available feature columns (some may be missing in edge cases)
    available = [c for c in FEATURE_COLS if c in feat.columns]
    missing   = [c for c in FEATURE_COLS if c not in feat.columns]
    if missing:
        log.warning("Missing feature columns (will be ignored): %s", missing)

    X = feat[available].values
    y = feat[TARGET_COL].values

    # ── Time-series cross-validation ────────────────────────────────────
    tscv = TimeSeriesSplit(n_splits=3)
    cv_maes = []
    cv_r2s  = []

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_tr, X_val = X[train_idx], X[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]

        dtrain = xgb.DMatrix(X_tr, label=y_tr, feature_names=available)
        dval   = xgb.DMatrix(X_val, label=y_val, feature_names=available)

        params = {
            "objective":        "reg:squarederror",
            "eval_metric":      "mae",
            "max_depth":        4,
            "learning_rate":    0.05,
            "n_estimators":     300,
            "subsample":        0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 5,
            "tree_method":      "hist",
            "device":           "cpu",
            "verbosity":        0,
        }
        model = xgb.train(
            params,
            dtrain,
            num_boost_round=300,
            evals=[(dval, "val")],
            early_stopping_rounds=30,
            verbose_eval=False,
        )
        preds = model.predict(dval)
        mae = mean_absolute_error(y_val, preds)
        r2  = r2_score(y_val, preds)
        cv_maes.append(mae)
        cv_r2s.append(r2)
        log.info("  Fold %d  MAE=%.1f  R²=%.3f", fold + 1, mae, r2)

    log.info("CV mean  MAE=%.1f ± %.1f  R²=%.3f",
             np.mean(cv_maes), np.std(cv_maes), np.mean(cv_r2s))

    # ── Final model on all data ──────────────────────────────────────────
    dtrain_full = xgb.DMatrix(X, label=y, feature_names=available)
    final_model = xgb.train(
        {**params, "verbosity": 0},
        dtrain_full,
        num_boost_round=model.best_iteration + 1,
    )

    # ── Save model ───────────────────────────────────────────────────────
    DATA_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    final_model.save_model(str(MODEL_PATH))
    log.info("Model saved → %s", MODEL_PATH)

    # ── Feature importance ───────────────────────────────────────────────
    importance = final_model.get_score(importance_type="gain")
    top = sorted(importance.items(), key=lambda x: -x[1])[:10]
    log.info("Top-10 features by gain:")
    for fname, score in top:
        log.info("  %-35s %.1f", fname, score)

    # ── Update calibration artifact → ml_ready = True ───────────────────
    artifact = calibrate()   # re-run calibration on combined data
    artifact["ml_ready"] = True
    artifact["n_days"]   = int(n_days)
    artifact["xgb_cv_mae_mean"] = round(float(np.mean(cv_maes)), 1)
    artifact["xgb_cv_r2_mean"]  = round(float(np.mean(cv_r2s)), 3)
    artifact["xgb_features"]    = available

    with open(ARTIFACT_PATH, "w") as f:
        json.dump(artifact, f, indent=2)

    log.info("Calibration updated → ml_ready=True")
    log.info("Restart the API to activate Phase 2 XGBoost scoring.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-only", action="store_true",
                        help="Train on real data only (requires >= 90 real days)")
    args = parser.parse_args()
    train(real_only=args.real_only)
