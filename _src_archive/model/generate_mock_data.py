"""
Mock data generator.

Generates synthetic (day, governorate) training data that:
  - Extends the real 18-day window back by ~90 days
  - Preserves the real statistical distribution (temps, reports)
  - Injects realistic correlations (hot days → more reports)
  - Does NOT overwrite real data — appends before it

The result is saved alongside the real merged dataset and used
only for Phase-2 XGBoost training. The real data is always kept
separate so you can track when the real-data-only gate opens.

Usage:
    python -m src.model.generate_mock_data
    python -m src.model.generate_mock_data --days 120
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.pipeline.config import DATA_PROCESSED, DATA_ARTIFACTS, GOVERNORATES
from src.pipeline.features import build_features

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

REAL_DATASET = DATA_PROCESSED / "merged_dataset.parquet"
MOCK_DATASET = DATA_PROCESSED / "mock_extended_dataset.parquet"
COMBINED     = DATA_PROCESSED / "combined_dataset.parquet"

# Tunisian summer climate priors (conservative, from ERA5 climatology)
CLIMATE = {
    # (mean, std) for each month
    "temp_max":  {6: (36, 3), 7: (39, 3.5), 8: (38, 3), 5: (30, 3), 4: (25, 3)},
    "temp_min":  {6: (22, 2), 7: (25, 2),   8: (25, 2), 5: (17, 2), 4: (13, 2)},
    "rh_max":    {6: (60, 8), 7: (55, 8),   8: (58, 8), 5: (65, 8), 4: (68, 8)},
    "wind_max":  {6: (20, 5), 7: (18, 5),   8: (19, 5), 5: (22, 5), 4: (24, 5)},
    "precip":    {6: (0.3,1), 7: (0.1,0.3), 8: (0.2,0.5), 5: (1.5,2), 4: (3,3)},
}

# Report volume model: base + heat bonus
# reports ~ Poisson(lambda) where lambda depends on temp_max
BASE_LAMBDA      = 300   # avg daily reports per governorate at 30°C
HEAT_MULTIPLIER  = 0.18  # each degree above 30°C multiplies lambda by (1 + 0.18)


def _climate_val(var: str, month: int, rng: np.random.Generator) -> float:
    fallback = {
        "temp_max": (35, 3), "temp_min": (22, 2),
        "rh_max": (58, 8),   "wind_max": (20, 5), "precip": (0.5, 1),
    }
    mean, std = CLIMATE.get(var, {}).get(month, fallback[var])
    return float(np.clip(rng.normal(mean, std), 0, None))


def generate_mock_rows(
    start: date,
    end: date,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate one synthetic row per (day, governorate) in [start, end]."""
    rows = []
    day = start
    while day <= end:
        month = day.month
        temp_max  = _climate_val("temp_max",  month, rng)
        temp_min  = _climate_val("temp_min",  month, rng)
        rh_max    = _climate_val("rh_max",    month, rng)
        wind_max  = _climate_val("wind_max",  month, rng)
        precip    = _climate_val("precip",    month, rng)

        # Clip so temp_min < temp_max
        temp_min = min(temp_min, temp_max - 4)
        temp_mean = (temp_max + temp_min) / 2

        # Heat-driven report volume
        heat_excess = max(temp_max - 30, 0)
        lam = BASE_LAMBDA * (1 + HEAT_MULTIPLIER * heat_excess)

        for gov in GOVERNORATES:
            # Per-governorate noise
            gov_lam = lam * rng.uniform(0.5, 1.8)
            reports_down = int(rng.poisson(gov_lam))

            rows.append({
                "day":                  day.isoformat(),
                "governorate":          gov,
                "temperature_2m_max":   round(temp_max, 1),
                "temperature_2m_min":   round(temp_min, 1),
                "temperature_2m_mean":  round(temp_mean, 1),
                "relative_humidity_2m_max": round(rh_max, 1),
                "relative_humidity_2m_min": round(rh_max * 0.6, 1),
                "wind_speed_10m_max":   round(wind_max, 1),
                "precipitation_sum":    round(max(precip, 0), 2),
                "et0_fao_evapotranspiration": round(rng.uniform(4, 9), 2),
                "reports_down":         reports_down,
                "reports_total":        reports_down,
                "is_mock":              True,
            })
        day += timedelta(days=1)

    return pd.DataFrame(rows)


def run(extra_days: int = 90, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)

    # Load real data to find its start date
    if not REAL_DATASET.exists():
        log.error("Real dataset not found — run download_data first")
        raise FileNotFoundError(REAL_DATASET)

    real_df = pd.read_parquet(REAL_DATASET)
    real_start = pd.to_datetime(real_df["day"]).min().date()
    mock_end   = real_start - timedelta(days=1)
    mock_start = mock_end - timedelta(days=extra_days - 1)

    log.info("Generating %d days of mock data: %s → %s", extra_days, mock_start, mock_end)
    mock_df = generate_mock_rows(mock_start, mock_end, rng)
    mock_df["is_mock"] = True

    # Tag real data
    real_df["is_mock"] = False

    # Combine: mock first (chronologically), then real
    combined = pd.concat([mock_df, real_df], ignore_index=True)
    combined.sort_values(["day", "governorate"], inplace=True)
    combined.reset_index(drop=True, inplace=True)

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    mock_df.to_parquet(MOCK_DATASET, index=False)
    combined.to_parquet(COMBINED, index=False)
    combined.to_csv(DATA_PROCESSED / "combined_dataset.csv", index=False)

    n_days = combined["day"].nunique()
    log.info("Mock dataset  → %s  (%d rows)", MOCK_DATASET.name, len(mock_df))
    log.info("Combined      → %s  (%d rows, %d days)", COMBINED.name, len(combined), n_days)
    log.info("ml_ready threshold (90 days): %s", "✅ YES" if n_days >= 90 else f"❌ NO ({n_days}/90)")
    return COMBINED


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90,
                        help="How many synthetic days to prepend (default 90)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run(args.days, args.seed)
