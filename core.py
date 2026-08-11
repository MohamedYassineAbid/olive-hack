"""
core.py — config, features, calibration, and risk scoring in one place.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT           = Path(__file__).resolve().parent
DATA_RAW       = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_ARTIFACTS = ROOT / "data" / "artifacts"

# ── API endpoints ─────────────────────────────────────────────────────────
import os
INCIDENT_BASE      = os.getenv("INCIDENT_BASE",      "https://api.incident.tn/api/v1")
METEO_ARCHIVE_BASE = os.getenv("METEO_ARCHIVE_BASE", "https://archive-api.open-meteo.com/v1/archive")
METEO_FORECAST_BASE= os.getenv("METEO_FORECAST_BASE","https://api.open-meteo.com/v1/forecast")

# ── All 24 Tunisian governorates (lat, lon) ───────────────────────────────
GOVERNORATES: dict[str, tuple[float, float]] = {
    "Ariana":      (36.8625, 10.1956), "Beja":        (36.7256,  9.1817),
    "Ben Arous":   (36.7533, 10.2281), "Bizerte":     (37.2744,  9.8739),
    "Gabes":       (33.8881, 10.0975), "Gafsa":       (34.4311,  8.7757),
    "Jendouba":    (36.5011,  8.7803), "Kairouan":    (35.6781, 10.0964),
    "Kasserine":   (35.1722,  8.8306), "Kebili":      (33.7044,  8.9694),
    "Kef":         (36.1822,  8.7147), "Mahdia":      (35.5047, 11.0622),
    "Manouba":     (36.8094, 10.0969), "Medenine":    (33.3550, 10.5050),
    "Monastir":    (35.7643, 10.8113), "Nabeul":      (36.4561, 10.7375),
    "Sfax":        (34.7406, 10.7603), "Sidi Bouzid": (35.0381,  9.4858),
    "Siliana":     (36.0844,  9.3708), "Sousse":      (35.8256, 10.6084),
    "Tataouine":   (32.9211, 10.4511), "Tozeur":      (33.9197,  8.1336),
    "Tunis":       (36.8065, 10.1815), "Zaghouan":    (36.4028, 10.1428),
}

ML_MIN_DAYS         = 90
DEFAULT_HIGH_TEMP   = 38.0
DEFAULT_EXTREME_TEMP= 42.0
DEFAULT_HIGH_RPT    = 2000
DEFAULT_EXTREME_RPT = 6000

# ── Risk levels ───────────────────────────────────────────────────────────
class RiskLevel(IntEnum):
    LOW = 0; MODERATE = 1; HIGH = 2; EXTREME = 3
    def label(self): return self.name.capitalize()

RISK_COLORS = {
    RiskLevel.LOW: "#4caf50", RiskLevel.MODERATE: "#ff9800",
    RiskLevel.HIGH: "#f44336", RiskLevel.EXTREME: "#7b1fa2",
}

# ── Features ──────────────────────────────────────────────────────────────

def heat_index(temp_max: float, rh_max: float) -> float:
    T, R = temp_max, rh_max
    if T < 27:
        return T
    hi = (-8.78469475556 + 1.61139411*T + 2.33854883889*R
          - 0.14611605*T*R - 0.012308094*T**2 - 0.0164248277778*R**2
          + 0.002211732*T**2*R + 0.00072546*T*R**2
          - 0.000003582*T**2*R**2)
    return round(hi, 2)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    feat = df.copy()
    rename = {
        "temperature_2m_max": "temp_max",   "temperature_2m_min": "temp_min",
        "temperature_2m_mean": "temp_mean", "relative_humidity_2m_max": "rh_max",
        "relative_humidity_2m_min": "rh_min","wind_speed_10m_max": "wind_max",
        "precipitation_sum": "precip",      "et0_fao_evapotranspiration": "et0",
    }
    feat.rename(columns={k: v for k, v in rename.items() if k in feat.columns}, inplace=True)
    if "temp_max" in feat.columns and "temp_min" in feat.columns:
        feat["temp_range"] = feat["temp_max"] - feat["temp_min"]
    if "rh_max" in feat.columns and "rh_min" in feat.columns:
        feat["rh_mean"] = (feat["rh_max"] + feat["rh_min"]) / 2.0
    if "temp_max" in feat.columns and "rh_max" in feat.columns:
        feat["heat_stress"] = feat.apply(
            lambda r: heat_index(r.get("temp_max", 25), r.get("rh_max", 50)), axis=1)
    feat["day"] = pd.to_datetime(feat["day"])
    feat["day_of_week"] = feat["day"].dt.dayofweek
    feat["month"]       = feat["day"].dt.month
    feat["is_weekend"]  = (feat["day_of_week"] >= 5).astype(int)
    feat["day"]         = feat["day"].dt.date.astype(str)
    for col in ("reports_down", "reports_total"):
        if col not in feat.columns:
            feat[col] = 0
    feat.sort_values(["governorate", "day"], inplace=True)
    grp = feat.groupby("governorate")["reports_down"]
    feat["reports_down_lag1"]  = grp.shift(1).fillna(0)
    feat["reports_down_lag2"]  = grp.shift(2).fillna(0)
    feat["reports_down_lag3"]  = grp.shift(3).fillna(0)
    feat["reports_down_roll3"] = grp.transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean()).fillna(0)
    feat["reports_down_roll7"] = grp.transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean()).fillna(0)
    national = (feat.groupby("day")["reports_down"].sum().reset_index()
                .rename(columns={"reports_down": "national_reports_down"}).sort_values("day"))
    national["national_reports_roll3"] = national["national_reports_down"].shift(1).rolling(3, min_periods=1).mean().fillna(0)
    feat = feat.merge(national, on="day", how="left")
    feat.sort_values(["day", "governorate"], inplace=True)
    feat.reset_index(drop=True, inplace=True)
    return feat


def build_single_row(*, day, governorate, temp_max, temp_min, temp_mean,
                     rh_max, rh_min=None, wind_max=None, precip=0.0, et0=None,
                     national_reports_down=0) -> pd.DataFrame:
    row = {
        "day": day, "governorate": governorate,
        "temp_max": temp_max, "temp_min": temp_min, "temp_mean": temp_mean,
        "rh_max": rh_max, "rh_min": rh_min or rh_max * 0.8,
        "wind_max": wind_max or 0.0, "precip": precip, "et0": et0 or 0.0,
        "reports_down": 0, "reports_total": 0,
        "national_reports_down": national_reports_down,
        "reports_down_lag1": 0, "reports_down_lag2": 0, "reports_down_lag3": 0,
        "reports_down_roll3": 0.0, "reports_down_roll7": 0.0,
        "national_reports_roll3": 0.0,
    }
    df = pd.DataFrame([row])
    df["day"] = pd.to_datetime(df["day"])
    df["day_of_week"] = df["day"].dt.dayofweek
    df["month"]       = df["day"].dt.month
    df["is_weekend"]  = (df["day_of_week"] >= 5).astype(int)
    df["day"]         = df["day"].dt.date.astype(str)
    df["temp_range"]  = temp_max - temp_min
    df["rh_mean"]     = (df["rh_max"] + df["rh_min"]) / 2.0
    df["heat_stress"] = heat_index(temp_max, rh_max)
    return df

# ── Calibration ───────────────────────────────────────────────────────────
ARTIFACT_PATH = DATA_ARTIFACTS / "calibration.json"

def _default_artifact():
    return {
        "n_days": 0, "ml_ready": False,
        "thresholds": {
            "temp_high_c": DEFAULT_HIGH_TEMP, "temp_extreme_c": DEFAULT_EXTREME_TEMP,
            "heat_stress_high": DEFAULT_HIGH_TEMP + 2, "heat_stress_extreme": DEFAULT_EXTREME_TEMP + 2,
            "reports_high": DEFAULT_HIGH_RPT, "reports_extreme": DEFAULT_EXTREME_RPT,
        },
        "gov_baseline_reports": {}, "feature_stats": {},
    }

def load_artifact() -> dict:
    if ARTIFACT_PATH.exists():
        with open(ARTIFACT_PATH) as f:
            return json.load(f)
    return _default_artifact()

def calibrate() -> dict:
    pq  = DATA_PROCESSED / "merged_dataset.parquet"
    csv = DATA_PROCESSED / "merged_dataset.csv"
    df  = pd.read_parquet(pq) if pq.exists() else (pd.read_csv(csv) if csv.exists() else None)
    if df is None or df.empty:
        artifact = _default_artifact()
    else:
        feat   = build_features(df)
        n_days = feat["day"].nunique()
        temps  = feat["temp_max"].dropna() if "temp_max" in feat.columns else pd.Series([DEFAULT_HIGH_TEMP])
        hs     = feat["heat_stress"].dropna() if "heat_stress" in feat.columns else pd.Series([DEFAULT_HIGH_TEMP+2])
        national = feat.groupby("day")["reports_down"].sum()
        nonzero  = national[national > 0]
        artifact = {
            "n_days": int(n_days),
            "ml_ready": n_days >= ML_MIN_DAYS,
            "thresholds": {
                "temp_high_c":         round(float(np.percentile(temps, 60)), 1),
                "temp_extreme_c":      round(float(np.percentile(temps, 85)), 1),
                "heat_stress_high":    round(float(np.percentile(hs, 60)), 1),
                "heat_stress_extreme": round(float(np.percentile(hs, 85)), 1),
                "reports_high":        round(float(np.percentile(nonzero, 40))) if len(nonzero) >= 3 else DEFAULT_HIGH_RPT,
                "reports_extreme":     round(float(np.percentile(nonzero, 75))) if len(nonzero) >= 3 else DEFAULT_EXTREME_RPT,
            },
            "gov_baseline_reports": {
                gov: float(grp.loc[grp["reports_down"] > 0, "reports_down"].mean() or 0)
                for gov, grp in feat.groupby("governorate")
            },
            "feature_stats": {},
        }
    DATA_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with open(ARTIFACT_PATH, "w") as f:
        json.dump(artifact, f, indent=2)
    log.info("Calibration → ml_ready=%s  n_days=%s", artifact["ml_ready"], artifact["n_days"])
    return artifact

# ── Risk scoring ──────────────────────────────────────────────────────────
W_TEMP = 0.30; W_HEAT = 0.25; W_RPT = 0.30; W_TREND = 0.15

@dataclass
class RiskResult:
    governorate: str; day: str; risk_level: RiskLevel; risk_score: float
    temp_max: float;  heat_stress: float; national_reports: int
    contributions: dict = field(default_factory=dict)
    explanation: str = ""; model_version: str = "rule_v1"

    def to_dict(self) -> dict:
        return {
            "governorate": self.governorate, "day": self.day,
            "risk_level": self.risk_level.label(), "risk_level_int": int(self.risk_level),
            "risk_score": round(self.risk_score, 4),
            "temp_max": self.temp_max, "heat_stress": self.heat_stress,
            "national_reports": self.national_reports,
            "contributions_pct": {k: round(v, 1) for k, v in self.contributions.items()},
            "explanation": self.explanation, "model_version": self.model_version,
            "risk_color": RISK_COLORS[self.risk_level],
        }

def _sigmoid(value, low, high):
    if high <= low: return 1.0 if value >= high else 0.0
    mid = (low + high) / 2.0
    return round(1 / (1 + math.exp(-3.0 * (value - mid) / ((high - low) / 2.0))), 4)

def _to_level(score):
    if score >= 0.75: return RiskLevel.EXTREME
    if score >= 0.50: return RiskLevel.HIGH
    if score >= 0.25: return RiskLevel.MODERATE
    return RiskLevel.LOW

class RiskScorer:
    def __init__(self):
        self._art  = load_artifact()
        self._thr  = self._art["thresholds"]
        self._xgb  = self._try_load_xgb() if self._art.get("ml_ready") else None
        log.info("RiskScorer  phase=%s  n_days=%s",
                 "2_xgboost" if self._xgb else "1_rule_based", self._art.get("n_days"))

    def score_row(self, row: dict) -> RiskResult:
        return self._score_xgb(row) if self._xgb else self._score_rules(row)

    def score_dataframe(self, df: pd.DataFrame) -> list[RiskResult]:
        return [self.score_row(r) for r in df.to_dict(orient="records")]

    def model_info(self) -> dict:
        return {
            "phase": "2_xgboost" if self._xgb else "1_rule_based",
            "ml_ready": self._art.get("ml_ready", False),
            "n_days": self._art.get("n_days", 0),
            "thresholds": self._thr,
            "weights": {"temperature": W_TEMP, "heat_stress": W_HEAT,
                        "reports": W_RPT, "trend": W_TREND},
        }

    def _score_rules(self, row):
        t   = self._thr
        tmp = float(row.get("temp_max", 25))
        hs  = float(row.get("heat_stress", tmp))
        nat = int(row.get("national_reports_down", row.get("national_reports", 0)))
        r3  = float(row.get("national_reports_roll3", 0))

        s_t  = _sigmoid(tmp, t["temp_high_c"],        t["temp_extreme_c"])
        s_h  = _sigmoid(hs,  t["heat_stress_high"],   t["heat_stress_extreme"])
        s_r  = _sigmoid(nat, t["reports_high"],        t["reports_extreme"])
        s_tr = min(max((nat / max(r3, 1) - 1) / 3.0, 0.0), 1.0)

        score  = round(min(max(W_TEMP*s_t + W_HEAT*s_h + W_RPT*s_r + W_TREND*s_tr, 0), 1), 4)
        level  = _to_level(score)
        total  = score if score > 0 else 1e-9

        parts = []
        if tmp >= t["temp_extreme_c"]:   parts.append(f"extreme temperature ({tmp:.1f}°C)")
        elif tmp >= t["temp_high_c"]:    parts.append(f"high temperature ({tmp:.1f}°C)")
        if hs  >= t["heat_stress_extreme"]: parts.append(f"extreme heat stress ({hs:.1f}°C)")
        elif hs >= t["heat_stress_high"]:   parts.append(f"elevated heat stress ({hs:.1f}°C)")
        if nat >= t["reports_extreme"]:  parts.append(f"very high outage reports ({nat:,})")
        elif nat >= t["reports_high"]:   parts.append(f"elevated outage reports ({nat:,})")
        if r3 > 0 and nat > r3 * 1.5:   parts.append(f"rising trend (vs 3d avg {r3:,.0f})")

        return RiskResult(
            governorate=str(row.get("governorate", "")),
            day=str(row.get("day", "")),
            risk_level=level, risk_score=score,
            temp_max=tmp, heat_stress=hs, national_reports=nat,
            contributions={
                "temperature": round(W_TEMP*s_t/total*100, 1),
                "heat_stress": round(W_HEAT*s_h/total*100, 1),
                "reports":     round(W_RPT *s_r/total*100, 1),
                "trend":       round(W_TREND*s_tr/total*100, 1),
            },
            explanation=f"Risk {level.label()} — " + ("; ".join(parts) if parts else "conditions normal."),
        )

    def _try_load_xgb(self):
        model_path = DATA_ARTIFACTS / "xgb_model.json"
        if not model_path.exists():
            return None
        try:
            import xgboost as xgb
            b = xgb.Booster(); b.load_model(str(model_path))
            return b
        except Exception as e:
            log.warning("XGBoost load failed: %s", e); return None

    def _score_xgb(self, row):
        import xgboost as xgb
        COLS = ["temp_max","temp_min","temp_range","rh_max","rh_mean","heat_stress",
                "wind_max","precip","et0","day_of_week","month","is_weekend",
                "reports_down_lag1","reports_down_lag2","reports_down_lag3",
                "reports_down_roll3","reports_down_roll7",
                "national_reports_down","national_reports_roll3"]
        vals = [[float(row.get(c, 0) or 0) for c in COLS]]
        score = float(self._xgb.predict(xgb.DMatrix(np.array(vals), feature_names=COLS))[0])
        score = round(min(max(score, 0), 1), 4)
        return RiskResult(
            governorate=str(row.get("governorate","")), day=str(row.get("day","")),
            risk_level=_to_level(score), risk_score=score,
            temp_max=float(row.get("temp_max",0)), heat_stress=float(row.get("heat_stress",0)),
            national_reports=int(row.get("national_reports_down",0)),
            explanation=f"XGBoost score={score:.3f}", model_version="xgb_v1",
        )

# ── HTML report renderer ──────────────────────────────────────────────────
_EMOJI = {RiskLevel.LOW:"✅", RiskLevel.MODERATE:"⚠️", RiskLevel.HIGH:"🔴", RiskLevel.EXTREME:"🚨"}

def render_national_report(results: list[RiskResult]) -> str:
    rows = sorted([r.to_dict() for r in results], key=lambda x: -x["risk_score"])
    report_date   = results[0].day if results else date.today().isoformat()
    model_version = results[0].model_version if results else "rule_v1"
    rows_html = "".join(f"""
    <tr>
      <td style='padding:9px 14px'><strong>{r['governorate']}</strong></td>
      <td style='padding:9px 14px'>
        <span style='background:{r['risk_color']};color:#fff;padding:2px 10px;border-radius:12px;font-size:0.8rem'>
          {r['risk_level']}
        </span>
      </td>
      <td style='padding:9px 14px'>{r['risk_score']:.3f}</td>
      <td style='padding:9px 14px'>{r['temp_max']}°C</td>
      <td style='padding:9px 14px'>{r['heat_stress']}°C</td>
      <td style='padding:9px 14px'>{r['national_reports']:,}</td>
      <td style='padding:9px 14px;font-size:0.78rem;color:#555'>{r['explanation']}</td>
    </tr>""" for r in rows)
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f9;color:#1a1a2e;padding:24px}}
h1{{font-size:1.5rem;margin-bottom:4px}}.sub{{color:#555;font-size:0.85rem;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
th{{background:#1a1a2e;color:#fff;padding:10px 14px;text-align:left;font-weight:600}}
td{{padding:9px 14px;border-bottom:1px solid #f0f0f0}}tr:last-child td{{border-bottom:none}}
tr:nth-child(even){{background:#fafbfc}}.footer{{margin-top:24px;font-size:0.75rem;color:#aaa;text-align:center}}
</style></head><body>
<h1>⚡ Electricity Outage Risk Report</h1>
<div class="sub">{report_date} · Model: {model_version} · hack-olive</div>
<table><thead><tr>
  <th>Governorate</th><th>Risk</th><th>Score</th>
  <th>🌡️ Temp</th><th>🥵 Heat Index</th><th>📋 Reports</th><th>Analysis</th>
</tr></thead><tbody>{rows_html}</tbody></table>
<div class="footer">hack-olive · Tunisia Electricity Risk · incident.tn + Open-Meteo</div>
</body></html>"""
