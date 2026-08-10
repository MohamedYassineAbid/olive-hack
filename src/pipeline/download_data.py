"""
Production data downloader.

Pulls electricity incident history from incident.tn and matching
historical weather from Open-Meteo, with retries, validation, and
structured output to data/raw/ and data/processed/.

Usage:
    python -m src.pipeline.download_data
    python -m src.pipeline.download_data --days 30
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.pipeline.config import (
    DATA_PROCESSED,
    DATA_RAW,
    GOVERNORATES,
    INCIDENT_BASE,
    INCIDENT_HISTORY_DAYS,
    METEO_ARCHIVE_BASE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── HTTP helpers ──────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(requests.HTTPError),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _get(url: str, params: dict | None = None) -> Any:
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code == 429:
        log.warning("Rate limited — retrying after back-off")
        resp.raise_for_status()
    resp.raise_for_status()
    return resp.json()


def _save_raw(name: str, data: Any) -> Path:
    path = DATA_RAW / f"{name}.json"
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info("Saved raw  → %s", path.name)
    return path


# ── incident.tn ───────────────────────────────────────────────────────────

def fetch_incident_history(days: int = INCIDENT_HISTORY_DAYS) -> list[dict]:
    """Return the flat list of row dicts from /history (electricity)."""
    log.info("Fetching incident.tn /history  days=%d", days)
    data = _get(
        f"{INCIDENT_BASE}/history",
        params={"type": "electricity", "days": days},
    )
    _save_raw("incident_history", data)

    rows = data.get("data", {}).get("rows", [])
    if not rows:
        log.warning("No rows returned from /history — check API or date range")
    log.info("  %d rows, %d distinct days",
             len(rows), len({r["day"] for r in rows}))
    return rows


def fetch_incident_analytics() -> dict:
    """Return the analytics payload (last ~90 days, bucketed)."""
    log.info("Fetching incident.tn /analytics")
    data = _get(f"{INCIDENT_BASE}/analytics", params={"type": "electricity"})
    _save_raw("incident_analytics", data)
    return data.get("data", {})


# ── Open-Meteo ────────────────────────────────────────────────────────────

METEO_DAILY_VARS = ",".join([
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "relative_humidity_2m_max",
    "relative_humidity_2m_min",
    "wind_speed_10m_max",
    "precipitation_sum",
    "et0_fao_evapotranspiration",
])


def fetch_weather_for_governorate(
    name: str,
    lat: float,
    lon: float,
    start: str,
    end: str,
) -> dict:
    """Fetch daily weather archive for one governorate."""
    data = _get(
        METEO_ARCHIVE_BASE,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start,
            "end_date": end,
            "daily": METEO_DAILY_VARS,
            "timezone": "Africa/Tunis",
        },
    )
    return data


def fetch_all_weather(
    start: str,
    end: str,
) -> dict[str, dict]:
    """Fetch weather for every governorate and return keyed by name."""
    results: dict[str, dict] = {}
    for gov, (lat, lon) in GOVERNORATES.items():
        log.info("  Weather  %-20s  %s → %s", gov, start, end)
        try:
            results[gov] = fetch_weather_for_governorate(gov, lat, lon, start, end)
        except Exception as exc:
            log.error("  Failed for %s: %s", gov, exc)
    _save_raw("weather_all_governorates", results)
    return results


# ── Merge & persist ───────────────────────────────────────────────────────

def _weather_to_daily_df(weather_by_gov: dict[str, dict]) -> "pd.DataFrame":
    """Convert raw Open-Meteo response dict into a long-format DataFrame."""
    import pandas as pd

    frames = []
    for gov, payload in weather_by_gov.items():
        daily = payload.get("daily", {})
        if not daily or "time" not in daily:
            continue
        df = pd.DataFrame(daily)
        df.rename(columns={"time": "day"}, inplace=True)
        df["governorate"] = gov
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _incident_to_daily_df(rows: list[dict]) -> "pd.DataFrame":
    """Convert /history rows to a DataFrame, normalising column names."""
    import pandas as pd

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Normalise: the API uses 'region' for governorate name
    if "region" in df.columns and "governorate" not in df.columns:
        df.rename(columns={"region": "governorate"}, inplace=True)

    df["day"] = pd.to_datetime(df["day"]).dt.date.astype(str)
    return df


def build_merged_dataset(
    incident_rows: list[dict],
    weather_by_gov: dict[str, dict],
) -> "pd.DataFrame":
    """
    Merge incident and weather data into one row-per-(day, governorate) table.
    Missing weather is forward-filled within each governorate (at most 2 days).
    Missing incident rows are filled with 0 reports.
    """
    import pandas as pd

    inc_df = _incident_to_daily_df(incident_rows)
    wx_df = _weather_to_daily_df(weather_by_gov)

    if inc_df.empty or wx_df.empty:
        log.warning("One or both data sources are empty — returning empty merge")
        return pd.DataFrame()

    merged = wx_df.merge(inc_df, on=["day", "governorate"], how="left")
    merged["reports_down"] = merged["reports_down"].fillna(0).astype(int)
    merged["reports_total"] = merged.get(
        "reports_total", merged["reports_down"]
    ).fillna(0).astype(int)

    # Forward-fill weather gaps (≤2 days) within each governorate
    for col in [c for c in merged.columns if c not in ("day", "governorate")]:
        merged[col] = (
            merged.groupby("governorate")[col]
            .transform(lambda s: s.ffill(limit=2))
        )

    merged.sort_values(["day", "governorate"], inplace=True)
    merged.reset_index(drop=True, inplace=True)
    return merged


def run(days: int = INCIDENT_HISTORY_DAYS) -> None:
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

    # 1. Incident data
    incident_rows = fetch_incident_history(days)
    fetch_incident_analytics()

    if not incident_rows:
        log.error("No incident data — aborting pipeline")
        sys.exit(1)

    # 2. Determine date window from actual incident data
    all_days = sorted({r["day"] for r in incident_rows})
    start, end = all_days[0], all_days[-1]
    log.info("Incident window: %s → %s  (%d days)", start, end, len(all_days))

    # 3. Weather for the same window
    weather = fetch_all_weather(start, end)

    # 4. Merge
    merged = build_merged_dataset(incident_rows, weather)
    if merged.empty:
        log.error("Merged dataset is empty — check raw files")
        sys.exit(1)

    out = DATA_PROCESSED / "merged_dataset.parquet"
    merged.to_parquet(out, index=False)
    log.info("Merged dataset → %s  (%d rows)", out.name, len(merged))

    csv_out = DATA_PROCESSED / "merged_dataset.csv"
    merged.to_csv(csv_out, index=False)
    log.info("CSV copy       → %s", csv_out.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download and merge all data")
    parser.add_argument("--days", type=int, default=INCIDENT_HISTORY_DAYS)
    args = parser.parse_args()
    run(args.days)
