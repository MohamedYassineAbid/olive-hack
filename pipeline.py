"""
pipeline.py — data download, merge, calibrate, evaluate, and CLI runner.

Usage:
    python pipeline.py                  # full run
    python pipeline.py --skip-download  # re-use existing data
    python pipeline.py --days 30
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core import (
    DATA_ARTIFACTS, DATA_PROCESSED, DATA_RAW,
    GOVERNORATES, INCIDENT_BASE, METEO_ARCHIVE_BASE,
    build_features, calibrate,
    RiskScorer, render_national_report,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

METEO_DAILY_VARS = ",".join([
    "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
    "relative_humidity_2m_max", "relative_humidity_2m_min",
    "wind_speed_10m_max", "precipitation_sum", "et0_fao_evapotranspiration",
])


# ── HTTP helper ───────────────────────────────────────────────────────────

@retry(retry=retry_if_exception_type(requests.HTTPError),
       wait=wait_exponential(multiplier=1, min=2, max=30),
       stop=stop_after_attempt(4), reraise=True)
def _get(url, params=None):
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _save_raw(name, data):
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    with open(DATA_RAW / f"{name}.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Download ──────────────────────────────────────────────────────────────

def fetch_incidents(days=90):
    log.info("Fetching incident.tn /history  days=%d", days)
    data = _get(f"{INCIDENT_BASE}/history", {"type": "electricity", "days": days})
    _save_raw("incident_history", data)
    rows = data.get("data", {}).get("rows", [])
    log.info("  %d rows, %d distinct days", len(rows), len({r["day"] for r in rows}))
    return rows


def fetch_analytics():
    data = _get(f"{INCIDENT_BASE}/analytics", {"type": "electricity"})
    _save_raw("incident_analytics", data)
    return data.get("data", {})


def fetch_weather(start, end):
    results = {}
    for gov, (lat, lon) in GOVERNORATES.items():
        log.info("  Weather  %-20s  %s → %s", gov, start, end)
        try:
            results[gov] = _get(METEO_ARCHIVE_BASE, {
                "latitude": lat, "longitude": lon,
                "start_date": start, "end_date": end,
                "daily": METEO_DAILY_VARS, "timezone": "Africa/Tunis",
            })
        except Exception as e:
            log.error("  Failed %s: %s", gov, e)
    _save_raw("weather_all_governorates", results)
    return results


# ── Merge ─────────────────────────────────────────────────────────────────

def merge(incident_rows, weather_by_gov):
    # Incident DataFrame
    inc = pd.DataFrame(incident_rows)
    if inc.empty:
        return pd.DataFrame()
    if "region" in inc.columns and "governorate" not in inc.columns:
        inc.rename(columns={"region": "governorate"}, inplace=True)
    inc["day"] = pd.to_datetime(inc["day"]).dt.date.astype(str)

    # Weather DataFrame
    wx_frames = []
    for gov, payload in weather_by_gov.items():
        daily = payload.get("daily", {})
        if not daily or "time" not in daily:
            continue
        df = pd.DataFrame(daily)
        df.rename(columns={"time": "day"}, inplace=True)
        df["governorate"] = gov
        wx_frames.append(df)
    if not wx_frames:
        return pd.DataFrame()
    wx = pd.concat(wx_frames, ignore_index=True)

    merged = wx.merge(inc, on=["day", "governorate"], how="left")
    merged["reports_down"]  = merged["reports_down"].fillna(0).astype(int)
    merged["reports_total"] = merged.get("reports_total", merged["reports_down"]).fillna(0).astype(int)
    for col in [c for c in merged.columns if c not in ("day", "governorate")]:
        merged[col] = merged.groupby("governorate")[col].transform(lambda s: s.ffill(limit=2))
    merged.sort_values(["day", "governorate"], inplace=True)
    merged.reset_index(drop=True, inplace=True)
    return merged


# ── Evaluate ──────────────────────────────────────────────────────────────

def evaluate():
    pq  = DATA_PROCESSED / "merged_dataset.parquet"
    csv = DATA_PROCESSED / "merged_dataset.csv"
    df  = pd.read_parquet(pq) if pq.exists() else (pd.read_csv(csv) if csv.exists() else None)
    if df is None:
        log.warning("No processed data for evaluation"); return {}

    feat   = build_features(df)
    n_days = feat["day"].nunique()
    national = feat.groupby("day")["reports_down"].sum().sort_index()

    def mae(a, b): return float(abs(a.values - b.values).mean())
    mae_y  = mae(national, national.shift(1).fillna(0))
    mae_r3 = mae(national, national.shift(1).rolling(3, min_periods=1).mean().fillna(0))

    scorer = RiskScorer()
    scores = pd.DataFrame([r.to_dict() for r in scorer.score_dataframe(feat)])
    risk_by_day = scores.groupby("day")["risk_score"].mean()
    nat_df = national.reset_index(); nat_df.columns = ["day", "actual"]
    merged = risk_by_day.reset_index().merge(nat_df, on="day")
    corr = merged[["risk_score", "actual"]].corr().iloc[0, 1]

    summary = {
        "n_days": int(n_days),
        "baseline_mae": {"naive_yesterday": round(mae_y, 1), "rolling_3_day": round(mae_r3, 1)},
        "rule_scorer_r": round(float(corr), 3) if not pd.isna(corr) else None,
    }
    DATA_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with open(DATA_ARTIFACTS / "evaluation_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    log.info("Eval  naive_MAE=%.1f  r=%.3f", mae_y, corr or 0)
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────

def run(days=90, skip_download=False):
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

    if not skip_download:
        log.info("═══ 1/4  Download ═══")
        rows = fetch_incidents(days)
        fetch_analytics()
        if not rows:
            log.error("No incident data — aborting"); sys.exit(1)
        all_days = sorted({r["day"] for r in rows})
        weather  = fetch_weather(all_days[0], all_days[-1])
        merged   = merge(rows, weather)
        if merged.empty:
            log.error("Empty merged dataset"); sys.exit(1)
        merged.to_parquet(DATA_PROCESSED / "merged_dataset.parquet", index=False)
        merged.to_csv(DATA_PROCESSED / "merged_dataset.csv", index=False)
        log.info("Merged  %d rows saved", len(merged))
    else:
        log.info("═══ 1/4  Skipped ═══")

    log.info("═══ 2/4  Calibrate ═══")
    art = calibrate()
    log.info("  n_days=%d  ml_ready=%s", art["n_days"], art["ml_ready"])

    log.info("═══ 3/4  Evaluate ═══")
    evaluate()

    log.info("═══ 4/4  Report ═══")
    pq  = DATA_PROCESSED / "merged_dataset.parquet"
    csv = DATA_PROCESSED / "merged_dataset.csv"
    df  = pd.read_parquet(pq) if pq.exists() else pd.read_csv(csv)
    feat = build_features(df)
    latest = feat[feat["day"] == feat["day"].max()]
    scorer  = RiskScorer()
    results = scorer.score_dataframe(latest)
    html    = render_national_report(results)
    out     = DATA_ARTIFACTS / f"national_report_{feat['day'].max()}.html"
    out.write_text(html, encoding="utf-8")
    log.info("  Report → %s", out.name)
    log.info("Pipeline complete.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--skip-download", action="store_true")
    a = p.parse_args()
    run(a.days, a.skip_download)
