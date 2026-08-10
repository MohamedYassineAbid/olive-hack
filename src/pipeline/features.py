"""
Shared feature engineering.

This module is the single source of truth for every feature used by
BOTH the Phase-1 rule scorer and the future XGBoost model.  Nothing
about risk thresholds or scoring lives here — only deterministic
transformations from raw columns to model-ready columns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── Heat-stress index (Apparent Temperature simplified) ──────────────────

def heat_stress_index(temp_max: float, rh_max: float) -> float:
    """
    Simplified heat index (°C) valid for temp_max ≥ 27 °C.
    Uses the Rothfusz regression; falls back to temp_max below threshold.

    Args:
        temp_max: Maximum 2 m air temperature (°C).
        rh_max:   Maximum relative humidity (%).

    Returns:
        Apparent temperature (°C).
    """
    T = temp_max
    R = rh_max
    if T < 27:
        return T
    HI = (
        -8.78469475556
        + 1.61139411 * T
        + 2.33854883889 * R
        - 0.14611605 * T * R
        - 0.012308094 * T ** 2
        - 0.0164248277778 * R ** 2
        + 0.002211732 * T ** 2 * R
        + 0.00072546 * T * R ** 2
        - 0.000003582 * T ** 2 * R ** 2
    )
    return round(HI, 2)


# ── Core feature builder ──────────────────────────────────────────────────

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform a merged (incident + weather) DataFrame into a feature
    DataFrame ready for scoring or ML training.

    Input columns expected (all optional — missing ones produce NaN):
        day, governorate,
        temperature_2m_max, temperature_2m_min, temperature_2m_mean,
        relative_humidity_2m_max, relative_humidity_2m_min,
        wind_speed_10m_max, precipitation_sum,
        et0_fao_evapotranspiration,
        reports_down, reports_total

    Output adds:
        temp_max, temp_min, temp_mean, temp_range,
        rh_max, rh_min, rh_mean,
        wind_max, precip, et0,
        heat_stress,
        day_of_week, month, is_weekend,
        reports_down, reports_total,
        reports_down_lag1, reports_down_lag2, reports_down_lag3,
        reports_down_roll3, reports_down_roll7,
        national_reports_down  (sum across all govs on that day),
        national_reports_roll3
    """
    feat = df.copy()

    # ── Rename weather columns to short names ────────────────────────────
    rename = {
        "temperature_2m_max": "temp_max",
        "temperature_2m_min": "temp_min",
        "temperature_2m_mean": "temp_mean",
        "relative_humidity_2m_max": "rh_max",
        "relative_humidity_2m_min": "rh_min",
        "wind_speed_10m_max": "wind_max",
        "precipitation_sum": "precip",
        "et0_fao_evapotranspiration": "et0",
    }
    feat.rename(columns={k: v for k, v in rename.items() if k in feat.columns},
                inplace=True)

    # ── Derived weather features ─────────────────────────────────────────
    if "temp_max" in feat.columns and "temp_min" in feat.columns:
        feat["temp_range"] = feat["temp_max"] - feat["temp_min"]

    if "rh_max" in feat.columns and "rh_min" in feat.columns:
        feat["rh_mean"] = (feat["rh_max"] + feat["rh_min"]) / 2.0

    if "temp_max" in feat.columns and "rh_max" in feat.columns:
        feat["heat_stress"] = feat.apply(
            lambda r: heat_stress_index(
                r.get("temp_max", np.nan),
                r.get("rh_max", np.nan),
            ),
            axis=1,
        )

    # ── Calendar features ────────────────────────────────────────────────
    feat["day"] = pd.to_datetime(feat["day"])
    feat["day_of_week"] = feat["day"].dt.dayofweek   # 0=Mon … 6=Sun
    feat["month"] = feat["day"].dt.month
    feat["is_weekend"] = (feat["day_of_week"] >= 5).astype(int)
    feat["day"] = feat["day"].dt.date.astype(str)     # back to string key

    # ── Ensure incident columns exist ────────────────────────────────────
    for col in ("reports_down", "reports_total"):
        if col not in feat.columns:
            feat[col] = 0

    # ── Per-governorate lags & rolling means ─────────────────────────────
    feat.sort_values(["governorate", "day"], inplace=True)

    grp = feat.groupby("governorate")["reports_down"]
    feat["reports_down_lag1"] = grp.shift(1).fillna(0)
    feat["reports_down_lag2"] = grp.shift(2).fillna(0)
    feat["reports_down_lag3"] = grp.shift(3).fillna(0)
    feat["reports_down_roll3"] = (
        grp.transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
        .fillna(0)
    )
    feat["reports_down_roll7"] = (
        grp.transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
        .fillna(0)
    )

    # ── National-level aggregates (join back onto per-gov rows) ──────────
    national = (
        feat.groupby("day")["reports_down"]
        .sum()
        .reset_index()
        .rename(columns={"reports_down": "national_reports_down"})
    )
    # national rolling-3 (lagged so no leakage)
    national = national.sort_values("day")
    national["national_reports_roll3"] = (
        national["national_reports_down"]
        .shift(1)
        .rolling(3, min_periods=1)
        .mean()
        .fillna(0)
    )
    feat = feat.merge(national, on="day", how="left")

    feat.sort_values(["day", "governorate"], inplace=True)
    feat.reset_index(drop=True, inplace=True)
    return feat


# ── Single-row helper (for real-time API calls) ───────────────────────────

def build_single_row(
    *,
    day: str,
    governorate: str,
    temp_max: float,
    temp_min: float,
    temp_mean: float,
    rh_max: float,
    rh_min: float | None = None,
    wind_max: float | None = None,
    precip: float = 0.0,
    et0: float | None = None,
    reports_down: int = 0,
    reports_total: int = 0,
    national_reports_down: int = 0,
) -> pd.DataFrame:
    """
    Build a single-row feature DataFrame from named keyword arguments.
    Lags and rolling means will be 0 (caller can override after the fact).
    """
    row = {
        "day": day,
        "governorate": governorate,
        "temp_max": temp_max,
        "temp_min": temp_min,
        "temp_mean": temp_mean,
        "rh_max": rh_max,
        "rh_min": rh_min if rh_min is not None else rh_max * 0.8,
        "wind_max": wind_max or 0.0,
        "precip": precip,
        "et0": et0 or 0.0,
        "reports_down": reports_down,
        "reports_total": reports_total,
        "national_reports_down": national_reports_down,
        "reports_down_lag1": 0,
        "reports_down_lag2": 0,
        "reports_down_lag3": 0,
        "reports_down_roll3": 0.0,
        "reports_down_roll7": 0.0,
        "national_reports_roll3": 0.0,
    }
    df = pd.DataFrame([row])
    df["day"] = pd.to_datetime(df["day"])
    df["day_of_week"] = df["day"].dt.dayofweek
    df["month"] = df["day"].dt.month
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    df["day"] = df["day"].dt.date.astype(str)
    df["temp_range"] = temp_max - temp_min
    df["rh_mean"] = (df["rh_max"] + df["rh_min"]) / 2.0
    df["heat_stress"] = heat_stress_index(temp_max, rh_max)
    return df
