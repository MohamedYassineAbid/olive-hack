"""
train_outage_model.py

Merges all three data sources:
  1. STEG scraped outage notices  (113 events, 11 days, 7 regions)
  2. incident.tn reports + weather (18 days, 24 governorates)
  3. Open-Meteo archive            (24 governorates, precise weather)

Trains two XGBoost models per STEG region:
  - outage_clf  : binary  → will there be an outage today?
  - outage_reg  : regression → predicted start hour

Then predicts the next 7 days and saves the forecast.

Usage:
    python train_outage_model.py
    python train_outage_model.py --predict-only   (skip training, use saved model)
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger(__name__)

ROOT      = Path(__file__).parent
ARTIFACTS = ROOT / "data" / "artifacts"

# ── STEG region → incident.tn governorates mapping ────────────────────────
# STEG posts outages by broad region; incident.tn reports by governorate.
# Each region is represented by its primary governorate for weather lookup.
REGION_MAP: dict[str, dict] = {
    "جهة تونس الكبرى":  {"lat": 36.8065, "lon": 10.1815, "govs": ["Tunis","Ariana","Ben Arous","Manouba"]},
    "جهة الشمال":        {"lat": 37.2744, "lon":  9.8739, "govs": ["Bizerte","Beja","Jendouba"]},
    "جهة الشمال الغربي": {"lat": 36.5011, "lon":  8.7803, "govs": ["Jendouba","Kef","Siliana"]},
    "جهة الوسط":         {"lat": 35.6781, "lon": 10.0964, "govs": ["Kairouan","Sousse","Monastir","Mahdia"]},
    "جهة صفاقس":         {"lat": 34.7406, "lon": 10.7603, "govs": ["Sfax"]},
    "جهة الجنوب":        {"lat": 33.8881, "lon": 10.0975, "govs": ["Gabes","Medenine","Tataouine"]},
    "جهة الجنوب الغربي": {"lat": 33.9197, "lon":  8.1336, "govs": ["Tozeur","Kebili","Gafsa","Sidi Bouzid","Kasserine"]},
}

METEO_VARS  = ("temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
               "relative_humidity_2m_max,wind_speed_10m_max,precipitation_sum")
FEATURE_COLS = [
    "dow", "month", "is_weekend",
    "temp_max", "temp_min", "temp_mean", "rh_max", "wind_max", "precip",
    "national_reports",     # incident.tn national total
    "region_reports",       # incident.tn reports for this region's govs
    "prev_day_outage",      # was there an outage in this region yesterday?
    "outages_last3",        # outage count in this region over last 3 days
]


# ── 1. Load STEG data ─────────────────────────────────────────────────────

def load_steg() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data/steg-outage-data/data/processed/steg_outages.csv")
    df["outage_date"] = pd.to_datetime(df["outage_date"])
    df["day_str"]     = df["outage_date"].dt.date.astype(str)
    df["start_h"]     = pd.to_datetime(df["planned_start"], format="%H:%M", errors="coerce").dt.hour.fillna(12)
    end_dt            = pd.to_datetime(df["planned_end"],   format="%H:%M", errors="coerce")
    start_dt          = pd.to_datetime(df["planned_start"], format="%H:%M", errors="coerce")
    df["duration_h"]  = ((end_dt - start_dt).dt.total_seconds() / 3600).clip(lower=0.5).fillna(2.0)
    df["region_std"]  = df["region"].str.strip()
    log.info("STEG: %d events, %d days, regions: %s",
             len(df), df["day_str"].nunique(), sorted(df["region_std"].unique()))
    return df


# ── 2. Load incident.tn data ──────────────────────────────────────────────

def load_incident() -> pd.DataFrame:
    pq  = ROOT / "data/processed/merged_dataset.parquet"
    csv = ROOT / "data/processed/merged_dataset.csv"
    df  = pd.read_parquet(pq) if pq.exists() else pd.read_csv(csv)
    df.rename(columns={
        "day": "day_str",
        "temperature_2m_max":      "temp_max",
        "temperature_2m_min":      "temp_min",
        "temperature_2m_mean":     "temp_mean",
        "relative_humidity_2m_max":"rh_max",
        "wind_speed_10m_max":      "wind_max",
        "precipitation_sum":       "precip",
    }, inplace=True)
    log.info("incident.tn: %d rows, %d days, %d govs",
             len(df), df["day_str"].nunique(), df["governorate"].nunique())
    return df


# ── 3. Fetch weather for STEG dates not in incident.tn ───────────────────

def fetch_meteo_archive(lat, lon, start, end) -> pd.DataFrame:
    try:
        r = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude": lat, "longitude": lon,
            "start_date": start, "end_date": end,
            "daily": METEO_VARS, "timezone": "Africa/Tunis",
        }, timeout=20)
        r.raise_for_status()
        d = r.json().get("daily", {})
        return pd.DataFrame(d).rename(columns={
            "time":"day_str","temperature_2m_max":"temp_max",
            "temperature_2m_min":"temp_min","temperature_2m_mean":"temp_mean",
            "relative_humidity_2m_max":"rh_max","wind_speed_10m_max":"wind_max",
            "precipitation_sum":"precip",
        })
    except Exception as e:
        log.warning("Meteo fetch failed (%s–%s): %s", start, end, e)
        return pd.DataFrame()


# ── 4. Build full training dataset ────────────────────────────────────────

def build_dataset(steg: pd.DataFrame, incident: pd.DataFrame) -> pd.DataFrame:
    all_steg_days    = sorted(steg["day_str"].unique())
    inc_days         = set(incident["day_str"].unique())
    missing_days     = [d for d in all_steg_days if d not in inc_days]

    # Build region-day grid from STEG dates
    all_regions = list(REGION_MAP.keys())
    grid = pd.DataFrame(
        [(d, r) for d in all_steg_days for r in all_regions],
        columns=["day_str", "region_std"]
    )
    dt = pd.to_datetime(grid["day_str"])
    grid["dow"]        = dt.dt.dayofweek
    grid["month"]      = dt.dt.month
    grid["is_weekend"] = (grid["dow"] >= 5).astype(int)

    # ── Labels from STEG ─────────────────────────────────────────────
    outage_agg = steg.groupby(["day_str","region_std"]).agg(
        has_outage =("start_h",  "count"),
        start_h    =("start_h",  "mean"),
        duration_h =("duration_h","mean"),
    ).reset_index()
    outage_agg["has_outage"] = (outage_agg["has_outage"] > 0).astype(int)
    grid = grid.merge(outage_agg, on=["day_str","region_std"], how="left")
    grid["has_outage"]  = grid["has_outage"].fillna(0).astype(int)
    grid["start_h"]     = grid["start_h"].fillna(12.0)
    grid["duration_h"]  = grid["duration_h"].fillna(0.0)

    # ── Lag features (prev outage) ────────────────────────────────────
    grid.sort_values(["region_std","day_str"], inplace=True)
    grp = grid.groupby("region_std")["has_outage"]
    grid["prev_day_outage"] = grp.shift(1).fillna(0)
    grid["outages_last3"]   = grp.transform(lambda s: s.shift(1).rolling(3, min_periods=1).sum()).fillna(0)

    # ── Weather per region ────────────────────────────────────────────
    wx_frames = []

    # From incident.tn (Jul 23+): average weather of govs in region
    for region, info in REGION_MAP.items():
        region_govs = [g for g in info["govs"] if g in incident["governorate"].unique()]
        if region_govs:
            wx = (incident[incident["governorate"].isin(region_govs)]
                  .groupby("day_str")[["temp_max","temp_min","temp_mean","rh_max","wind_max","precip"]]
                  .mean().reset_index())
            wx["region_std"] = region
            wx_frames.append(wx)

    # For STEG-only days (Jul 18–22) fetch directly
    if missing_days:
        start_miss, end_miss = min(missing_days), max(missing_days)
        for region, info in REGION_MAP.items():
            wx = fetch_meteo_archive(info["lat"], info["lon"], start_miss, end_miss)
            if not wx.empty:
                wx["region_std"] = region
                wx_frames.append(wx)

    if wx_frames:
        weather = pd.concat(wx_frames, ignore_index=True)
        # Deduplicate (keep incident.tn version when both exist)
        weather = weather.sort_values("day_str").drop_duplicates(
            subset=["day_str","region_std"], keep="last")
        grid = grid.merge(weather, on=["day_str","region_std"], how="left")
    else:
        for col in ["temp_max","temp_min","temp_mean","rh_max","wind_max","precip"]:
            grid[col] = 35.0 if "temp" in col else 0.0

    # ── National + region incident reports ────────────────────────────
    national = incident.groupby("day_str")["reports_down"].sum().reset_index()
    national.columns = ["day_str","national_reports"]
    grid = grid.merge(national, on="day_str", how="left")
    grid["national_reports"] = grid["national_reports"].fillna(0)

    for region, info in REGION_MAP.items():
        region_govs = info["govs"]
        reg_reports = (incident[incident["governorate"].isin(region_govs)]
                       .groupby("day_str")["reports_down"].sum().reset_index())
        reg_reports.columns = ["day_str","region_reports_tmp"]
        mask = grid["region_std"] == region
        grid = grid.merge(reg_reports, on="day_str", how="left")
        grid.loc[mask, "region_reports"] = grid.loc[mask, "region_reports_tmp"]
        grid.drop(columns="region_reports_tmp", inplace=True)

    grid["region_reports"] = grid["region_reports"].fillna(0)
    grid = grid.fillna(0)

    log.info("Dataset: %d rows | %d outage | %d no-outage | features: %s",
             len(grid), grid["has_outage"].sum(), (grid["has_outage"]==0).sum(),
             FEATURE_COLS)
    return grid


# ── 5. Train ──────────────────────────────────────────────────────────────

def train_models(df: pd.DataFrame):
    try:
        import xgboost as xgb
    except ImportError:
        log.error("XGBoost not installed: pip install 'xgboost<2.1.0'")
        raise

    available = [c for c in FEATURE_COLS if c in df.columns]
    X     = df[available].values.astype(float)
    y_clf = df["has_outage"].values
    y_reg = df["start_h"].values

    # Classifier
    dtrain = xgb.DMatrix(X, label=y_clf, feature_names=available)
    clf = xgb.train({
        "objective": "binary:logistic", "eval_metric": "logloss",
        "max_depth": 4, "learning_rate": 0.08, "subsample": 0.85,
        "colsample_bytree": 0.8, "min_child_weight": 2,
        "tree_method": "hist", "verbosity": 0,
    }, dtrain, num_boost_round=300)

    # Regressor (start hour, only on outage rows)
    out_df = df[df["has_outage"] == 1]
    X_reg  = out_df[available].values.astype(float)
    dreg   = xgb.DMatrix(X_reg, label=out_df["start_h"].values, feature_names=available)
    reg = xgb.train({
        "objective": "reg:squarederror", "eval_metric": "mae",
        "max_depth": 4, "learning_rate": 0.08,
        "tree_method": "hist", "verbosity": 0,
    }, dreg, num_boost_round=300)

    # Accuracy
    probs = clf.predict(dtrain)
    acc   = ((probs >= 0.5).astype(int) == y_clf).mean()
    log.info("Train accuracy: %.1f%%  |  outage rows: %d  |  features: %s",
             acc*100, int(y_clf.sum()), available)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    clf.save_model(str(ARTIFACTS / "outage_clf.json"))
    reg.save_model(str(ARTIFACTS / "outage_reg.json"))

    meta = {
        "feature_cols":   available,
        "all_regions":    list(REGION_MAP.keys()),
        "region_map":     {k: {"lat": v["lat"], "lon": v["lon"], "govs": v["govs"]}
                           for k, v in REGION_MAP.items()},
        "train_accuracy": round(float(acc), 3),
        "n_train_rows":   int(len(df)),
        "n_outage_rows":  int(y_clf.sum()),
        "trained_at":     datetime.now().isoformat(),
        "data_sources":   ["steg_scrape", "incident_tn", "open_meteo"],
    }
    with open(ARTIFACTS / "outage_model_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    log.info("Saved: outage_clf.json, outage_reg.json, outage_model_meta.json")
    return clf, reg, meta


# ── 6. Predict next 7 days ────────────────────────────────────────────────

def predict_7_days(clf=None, reg=None, meta=None) -> pd.DataFrame:
    import xgboost as xgb

    if clf is None:
        clf = xgb.Booster(); clf.load_model(str(ARTIFACTS / "outage_clf.json"))
        reg = xgb.Booster(); reg.load_model(str(ARTIFACTS / "outage_reg.json"))
        with open(ARTIFACTS / "outage_model_meta.json", encoding="utf-8") as f:
            meta = json.load(f)

    feat_cols   = meta["feature_cols"]
    all_regions = meta["all_regions"]
    region_map  = meta["region_map"]
    today       = datetime.today().date()
    future      = [str(today + timedelta(days=i+1)) for i in range(7)]

    # Fetch forecast weather per region
    rows = []
    for region in all_regions:
        info = region_map[region]
        try:
            r = requests.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": info["lat"], "longitude": info["lon"],
                "timezone": "Africa/Tunis", "forecast_days": 8,
                "daily": METEO_VARS,
            }, timeout=15)
            r.raise_for_status()
            d = r.json().get("daily", {})
            for i, ds in enumerate(d.get("time", [])):
                if ds not in future:
                    continue
                dt = datetime.strptime(ds, "%Y-%m-%d")
                rows.append({
                    "day_str":    ds,
                    "region_std": region,
                    "dow":        dt.weekday(),
                    "month":      dt.month,
                    "is_weekend": int(dt.weekday() >= 5),
                    "temp_max":   d.get("temperature_2m_max",   [35]*8)[i],
                    "temp_min":   d.get("temperature_2m_min",   [25]*8)[i],
                    "temp_mean":  d.get("temperature_2m_mean",  [30]*8)[i],
                    "rh_max":     d.get("relative_humidity_2m_max",[55]*8)[i],
                    "wind_max":   d.get("wind_speed_10m_max",   [15]*8)[i],
                    "precip":     (d.get("precipitation_sum",   [0]*8)[i] or 0),
                    "national_reports":  0,   # unknown for future
                    "region_reports":    0,
                    "prev_day_outage":   0,
                    "outages_last3":     0,
                })
        except Exception as e:
            log.warning("Forecast fetch failed %s: %s", region, e)

    if not rows:
        log.error("No forecast data")
        return pd.DataFrame()

    pred_df  = pd.DataFrame(rows).fillna(0)
    available = [c for c in feat_cols if c in pred_df.columns]
    dmat     = xgb.DMatrix(pred_df[available].values.astype(float), feature_names=available)

    pred_df["outage_prob"]    = clf.predict(dmat).round(3)
    pred_df["pred_start_h"]   = reg.predict(dmat).clip(0, 23).round().astype(int)
    pred_df["outage_likely"]  = pred_df["outage_prob"] >= 0.50

    def window(h):
        return f"{int(h):02d}:00 – {min(int(h)+2,23):02d}:00"

    pred_df["time_window"] = pred_df.apply(
        lambda r: window(r["pred_start_h"]) if r["outage_likely"] else "—", axis=1)

    result = pred_df[[
        "day_str","region_std","outage_prob","outage_likely",
        "pred_start_h","time_window","temp_max","rh_max",
    ]].sort_values(["day_str","outage_prob"], ascending=[True,False]).reset_index(drop=True)

    result.to_csv(ARTIFACTS / "outage_forecast_7day.csv", index=False)
    log.info("Forecast saved → outage_forecast_7day.csv")

    # Also save as JSON for API
    out = {}
    for _, r in result.iterrows():
        d = r["day_str"]
        out.setdefault(d, [])
        out[d].append({
            "region":        r["region_std"],
            "outage_prob":   float(r["outage_prob"]),
            "outage_likely": bool(r["outage_likely"]),
            "time_window":   r["time_window"],
            "temp_max":      float(r["temp_max"]),
        })
    with open(ARTIFACTS / "outage_forecast_7day.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log.info("Forecast JSON → outage_forecast_7day.json")
    return result


# ── 7. Console summary ────────────────────────────────────────────────────

def print_forecast(df: pd.DataFrame):
    print("\n" + "="*72)
    print("  7-DAY ELECTRICITY OUTAGE FORECAST  (trained on STEG + incident.tn + weather)")
    print("="*72)
    for day, grp in df.groupby("day_str"):
        likely = grp[grp["outage_likely"]]
        print(f"\n  📅  {day}")
        if likely.empty:
            print("      ✅  No outages predicted")
        else:
            for _, r in likely.iterrows():
                bar = "█" * int(r["outage_prob"] * 10)
                print(f"      ⚡  {r['region_std']:<28}  "
                      f"{r['outage_prob']:.0%}  {bar:<10}  "
                      f"window: {r['time_window']}  "
                      f"🌡️ {r['temp_max']:.0f}°C")


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--predict-only", action="store_true",
                   help="Skip training, load saved model and predict")
    args = p.parse_args()

    if args.predict_only:
        log.info("Loading saved model and predicting...")
        forecast = predict_7_days()
    else:
        log.info("=== Step 1/4  Load STEG data ===")
        steg = load_steg()

        log.info("=== Step 2/4  Load incident.tn data ===")
        incident = load_incident()

        log.info("=== Step 3/4  Build merged training dataset ===")
        df = build_dataset(steg, incident)

        log.info("=== Step 4/4  Train & predict ===")
        clf, reg, meta = train_models(df)
        forecast = predict_7_days(clf, reg, meta)

    print_forecast(forecast)
