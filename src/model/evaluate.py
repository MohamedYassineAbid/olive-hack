"""
Evaluation module.

Runs baseline comparisons and backtests the rule scorer against the
real 18-day incident history. Honest about what can and cannot be
validated with a short time series.

Usage:
    python -m src.model.evaluate
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.pipeline.config import DATA_ARTIFACTS, DATA_PROCESSED
from src.pipeline.features import build_features
from src.model.risk_model import RiskScorer

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")


# ── Baselines ─────────────────────────────────────────────────────────────

def naive_yesterday(series: pd.Series) -> pd.Series:
    """Predict today = yesterday."""
    return series.shift(1).fillna(0)


def rolling_mean_baseline(series: pd.Series, window: int = 7) -> pd.Series:
    """Predict today = rolling mean of last `window` days (lagged)."""
    return series.shift(1).rolling(window, min_periods=1).mean().fillna(0)


def national_mae(actual: pd.Series, predicted: pd.Series) -> float:
    return float(np.abs(actual.values - predicted.values).mean())


# ── Main evaluation ───────────────────────────────────────────────────────

def run_evaluation() -> dict:
    pq  = DATA_PROCESSED / "merged_dataset.parquet"
    csv = DATA_PROCESSED / "merged_dataset.csv"

    if pq.exists():
        df = pd.read_parquet(pq)
    elif csv.exists():
        df = pd.read_csv(csv)
    else:
        log.error("No processed dataset found — run download_data first")
        return {}

    feat = build_features(df)
    n_days = feat["day"].nunique()
    log.info("Evaluating on %d days  (%d gov-day rows)", n_days, len(feat))

    # ── National daily series ─────────────────────────────────────────────
    national = (
        feat.groupby("day")["reports_down"]
        .sum()
        .reset_index()
        .sort_values("day")
        .set_index("day")["reports_down"]
    )

    mae_yesterday = national_mae(national, naive_yesterday(national))
    mae_roll7     = national_mae(national, rolling_mean_baseline(national, 7))
    mae_roll3     = national_mae(national, rolling_mean_baseline(national, 3))

    log.info("Baseline MAE (national daily reports_down):")
    log.info("  Naive yesterday:  %8.1f", mae_yesterday)
    log.info("  Rolling 3-day:    %8.1f", mae_roll3)
    log.info("  Rolling 7-day:    %8.1f", mae_roll7)

    # ── Rule scorer backtest ──────────────────────────────────────────────
    scorer = RiskScorer()
    results = scorer.score_dataframe(feat)
    scores_df = pd.DataFrame([r.to_dict() for r in results])

    risk_by_day = scores_df.groupby("day")["risk_score"].mean().reset_index()
    national_df = national.reset_index()
    national_df.columns = ["day", "actual_reports"]
    merged = risk_by_day.merge(national_df, on="day")

    corr = merged[["risk_score", "actual_reports"]].corr().iloc[0, 1]
    log.info("Rule scorer vs actual reports — Pearson r = %.3f", corr)

    # ── Caveats for short series ──────────────────────────────────────────
    caveats = []
    if n_days < 30:
        caveats.append(
            f"Only {n_days} days of history — baseline MAE estimates are "
            "high-variance; do not over-interpret."
        )
    if n_days < 90:
        caveats.append(
            "Supervised ML train/val/test split requires >= 90 days. "
            f"Current: {n_days}. Rule-based Phase-1 scorer is in use."
        )

    summary = {
        "n_days":          n_days,
        "n_rows":          len(feat),
        "baseline_mae": {
            "naive_yesterday": round(mae_yesterday, 1),
            "rolling_3_day":   round(mae_roll3, 1),
            "rolling_7_day":   round(mae_roll7, 1),
        },
        "rule_scorer_correlation_r": round(corr, 3) if not np.isnan(corr) else None,
        "caveats": caveats,
    }

    out = DATA_ARTIFACTS / "evaluation_summary.json"
    DATA_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    log.info("Evaluation summary → %s", out)
    return summary


if __name__ == "__main__":
    result = run_evaluation()
    print(json.dumps(result, indent=2))
