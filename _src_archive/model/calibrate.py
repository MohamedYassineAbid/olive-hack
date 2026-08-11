"""
Calibration module.

Reads the merged dataset, derives empirical risk thresholds from the
actual incident-report distribution, and saves a JSON artifact that
the risk scorer loads at startup.

If the dataset has >= ML_MIN_DAYS unique days the artifact also sets
`ml_ready: true`, which triggers XGBoost training instead of rules.

Usage:
    python -m src.model.calibrate
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.pipeline.config import (
    DATA_ARTIFACTS,
    DATA_PROCESSED,
    DEFAULT_EXTREME_TEMP_C,
    DEFAULT_HIGH_TEMP_C,
    DEFAULT_REPORTS_EXTREME,
    DEFAULT_REPORTS_HIGH,
    ML_MIN_DAYS,
)
from src.pipeline.features import build_features

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

ARTIFACT_PATH = DATA_ARTIFACTS / "calibration.json"


def load_processed() -> pd.DataFrame | None:
    pq = DATA_PROCESSED / "merged_dataset.parquet"
    csv = DATA_PROCESSED / "merged_dataset.csv"
    if pq.exists():
        return pd.read_parquet(pq)
    if csv.exists():
        return pd.read_csv(csv)
    return None


def calibrate() -> dict:
    """
    Derive thresholds from real data (or fall back to hard-coded defaults)
    and write data/artifacts/calibration.json.
    """
    df = load_processed()

    if df is None or df.empty:
        log.warning("No processed data found — using hard-coded defaults")
        artifact = _default_artifact()
        _save(artifact)
        return artifact

    feat = build_features(df)
    n_days = feat["day"].nunique()
    log.info("Calibrating on %d governorate-days  (%d unique calendar days)",
             len(feat), n_days)

    # ── Temperature thresholds ────────────────────────────────────────────
    if "temp_max" in feat.columns:
        temps = feat["temp_max"].dropna()
        temp_high    = float(np.percentile(temps, 60))
        temp_extreme = float(np.percentile(temps, 85))
    else:
        temp_high, temp_extreme = DEFAULT_HIGH_TEMP_C, DEFAULT_EXTREME_TEMP_C

    # ── National daily report thresholds ─────────────────────────────────
    if "national_reports_down" in feat.columns:
        national = feat.groupby("day")["reports_down"].sum()
        nonzero = national[national > 0]
        if len(nonzero) >= 3:
            reports_high    = float(np.percentile(nonzero, 40))
            reports_extreme = float(np.percentile(nonzero, 75))
        else:
            reports_high    = DEFAULT_REPORTS_HIGH
            reports_extreme = DEFAULT_REPORTS_EXTREME
    else:
        reports_high    = DEFAULT_REPORTS_HIGH
        reports_extreme = DEFAULT_REPORTS_EXTREME

    # ── Heat-stress thresholds ────────────────────────────────────────────
    if "heat_stress" in feat.columns:
        hs = feat["heat_stress"].dropna()
        hs_high    = float(np.percentile(hs, 60))
        hs_extreme = float(np.percentile(hs, 85))
    else:
        hs_high, hs_extreme = temp_high + 2, temp_extreme + 2

    # ── Per-governorate baseline (mean reports when non-zero) ─────────────
    gov_baseline: dict[str, float] = {}
    if "governorate" in feat.columns and "reports_down" in feat.columns:
        for gov, grp in feat.groupby("governorate"):
            nonzero_rows = grp.loc[grp["reports_down"] > 0, "reports_down"]
            gov_baseline[gov] = float(nonzero_rows.mean()) if len(nonzero_rows) else 0.0

    artifact = {
        "n_days": int(n_days),
        "ml_ready": n_days >= ML_MIN_DAYS,
        "thresholds": {
            "temp_high_c":         round(temp_high, 1),
            "temp_extreme_c":      round(temp_extreme, 1),
            "heat_stress_high":    round(hs_high, 1),
            "heat_stress_extreme": round(hs_extreme, 1),
            "reports_high":        round(reports_high),
            "reports_extreme":     round(reports_extreme),
        },
        "gov_baseline_reports": gov_baseline,
        # Feature means/stds for future normalisation
        "feature_stats": _feature_stats(feat),
    }

    _save(artifact)
    log.info("Calibration artifact → %s  (ml_ready=%s)", ARTIFACT_PATH, artifact["ml_ready"])
    return artifact


def _default_artifact() -> dict:
    return {
        "n_days": 0,
        "ml_ready": False,
        "thresholds": {
            "temp_high_c":         DEFAULT_HIGH_TEMP_C,
            "temp_extreme_c":      DEFAULT_EXTREME_TEMP_C,
            "heat_stress_high":    DEFAULT_HIGH_TEMP_C + 2,
            "heat_stress_extreme": DEFAULT_EXTREME_TEMP_C + 2,
            "reports_high":        DEFAULT_REPORTS_HIGH,
            "reports_extreme":     DEFAULT_REPORTS_EXTREME,
        },
        "gov_baseline_reports": {},
        "feature_stats": {},
    }


def _feature_stats(feat: pd.DataFrame) -> dict:
    numeric_cols = feat.select_dtypes(include=[np.number]).columns.tolist()
    stats: dict[str, dict] = {}
    for col in numeric_cols:
        s = feat[col].dropna()
        if len(s):
            stats[col] = {"mean": round(float(s.mean()), 4),
                          "std":  round(float(s.std()), 4)}
    return stats


def _save(artifact: dict) -> None:
    DATA_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with open(ARTIFACT_PATH, "w") as f:
        json.dump(artifact, f, indent=2)


def load_artifact() -> dict:
    """Load calibration artifact, falling back to defaults if absent."""
    if ARTIFACT_PATH.exists():
        with open(ARTIFACT_PATH) as f:
            return json.load(f)
    log.warning("Calibration artifact not found — using hard-coded defaults")
    return _default_artifact()


if __name__ == "__main__":
    calibrate()
