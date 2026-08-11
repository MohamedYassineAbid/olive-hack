"""
api.py — FastAPI app, all endpoints.

Run:
    uvicorn api:app --reload --port 8000
    
Endpoints:
    GET  /health
    GET  /model/info
    POST /predict
    POST /predict/batch
    GET  /daily/score          fetch + score all 24 governorates (used by n8n)
    GET  /forecast/governorate 7-day forecast for one governorate
    POST /report/national/json HTML report as JSON (used by n8n email)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date as date_cls
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from core import (
    GOVERNORATES, INCIDENT_BASE, METEO_FORECAST_BASE,
    RiskResult, RiskScorer,
    build_single_row, render_national_report,
)

log = logging.getLogger(__name__)
APP_VERSION = "2.0.0"

# ── Schemas ───────────────────────────────────────────────────────────────

class WeatherInput(BaseModel):
    governorate: str
    day: str = Field(..., examples=["2026-08-10"])
    temp_max:  float = Field(..., ge=-10, le=60)
    temp_min:  float = Field(..., ge=-10, le=55)
    temp_mean: float = Field(..., ge=-10, le=58)
    rh_max:    float = Field(..., ge=0, le=100)
    rh_min:    float | None = None
    wind_max:  float | None = None
    precip:    float = 0.0
    et0:       float | None = None
    national_reports_down:  int   = 0
    national_reports_roll3: float = 0.0
    reports_down_lag1: int   = 0
    reports_down_lag2: int   = 0
    reports_down_lag3: int   = 0
    reports_down_roll3: float = 0.0
    reports_down_roll7: float = 0.0

    @field_validator("day")
    @classmethod
    def validate_date(cls, v):
        try: date_cls.fromisoformat(v)
        except ValueError: raise ValueError(f"day must be YYYY-MM-DD, got {v!r}")
        return v


class BatchRequest(BaseModel):
    observations: list[WeatherInput] = Field(..., min_length=1, max_length=200)


# ── App & scorer ──────────────────────────────────────────────────────────

_scorer: RiskScorer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scorer
    _scorer = RiskScorer()
    yield
    _scorer = None


app = FastAPI(
    title="Electricity Outage Risk API",
    version=APP_VERSION,
    description="Tunisia electricity outage risk — 24 governorates, rule-based Phase 1, XGBoost Phase 2.",
    lifespan=lifespan,
)


def scorer() -> RiskScorer:
    if _scorer is None:
        raise HTTPException(503, "Scorer not ready")
    return _scorer


def _obs_to_row(obs: WeatherInput) -> dict:
    row = build_single_row(
        day=obs.day, governorate=obs.governorate,
        temp_max=obs.temp_max, temp_min=obs.temp_min, temp_mean=obs.temp_mean,
        rh_max=obs.rh_max, rh_min=obs.rh_min, wind_max=obs.wind_max,
        precip=obs.precip, et0=obs.et0,
        national_reports_down=obs.national_reports_down,
    ).to_dict(orient="records")[0]
    row.update({
        "national_reports_roll3": obs.national_reports_roll3,
        "reports_down_lag1": obs.reports_down_lag1,
        "reports_down_lag2": obs.reports_down_lag2,
        "reports_down_lag3": obs.reports_down_lag3,
        "reports_down_roll3": obs.reports_down_roll3,
        "reports_down_roll7": obs.reports_down_roll7,
    })
    return row


# ── Routes ────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health():
    info = scorer().model_info()
    return {"status": "ok", "model_phase": info["phase"],
            "ml_ready": info["ml_ready"], "n_days": info["n_days"],
            "version": APP_VERSION}


@app.get("/model/info", tags=["meta"])
def model_info():
    return scorer().model_info()


@app.post("/predict", tags=["prediction"])
def predict(obs: WeatherInput):
    return scorer().score_row(_obs_to_row(obs)).to_dict()


@app.post("/predict/batch", tags=["prediction"])
def predict_batch(body: BatchRequest):
    s = scorer()
    preds = [s.score_row(_obs_to_row(o)).to_dict() for o in body.observations]
    return {"count": len(preds), "predictions": preds}


@app.post("/report/national/json", tags=["report"])
def report_national_json(body: BatchRequest):
    """Returns {html, count} — use this from n8n for email body."""
    s = scorer()
    results = [s.score_row(_obs_to_row(o)) for o in body.observations]
    return {"html": render_national_report(results), "count": len(results)}


@app.post("/report/national", response_class=HTMLResponse, tags=["report"])
def report_national(body: BatchRequest):
    s = scorer()
    results = [s.score_row(_obs_to_row(o)) for o in body.observations]
    return HTMLResponse(render_national_report(results))


# ── Live data endpoints (used by n8n) ─────────────────────────────────────

def _fetch_incident_baseline(target_date: str) -> tuple[int, float]:
    """Return (national_reports_today, 3day_rolling_avg)."""
    try:
        with httpx.Client(timeout=15) as client:
            inc = client.get(f"{INCIDENT_BASE}/history",
                             params={"type": "electricity", "days": 7}).json()
        rows = inc.get("data", {}).get("rows", [])
        national = sum(r.get("reports_down", 0) for r in rows if r.get("day") == target_date)
        days3    = sorted({r["day"] for r in rows})[-3:]
        roll3    = sum(r.get("reports_down", 0) for r in rows if r.get("day") in days3)
        roll3   /= max(len(days3) * 24, 1)
        return national, roll3
    except Exception as e:
        log.warning("Incident fetch failed: %s", e)
        return 0, 0.0


def _fetch_weather_row(gov: str, lat: float, lon: float,
                       target_date: str, client: httpx.Client,
                       national: int, forecast_days: int = 1) -> list[dict]:
    """Fetch Open-Meteo for one governorate; return list of raw weather dicts."""
    wx = client.get(METEO_FORECAST_BASE, params={
        "latitude": lat, "longitude": lon, "timezone": "Africa/Tunis",
        "forecast_days": forecast_days,
        "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
                 "relative_humidity_2m_max,wind_speed_10m_max,precipitation_sum",
    }).json()
    d = wx.get("daily", {})
    return [{"date": d["time"][i], "gov": gov, "lat": lat, "lon": lon,
             "temp_max":  d["temperature_2m_max"][i],
             "temp_min":  d["temperature_2m_min"][i],
             "temp_mean": d["temperature_2m_mean"][i],
             "rh_max":    d["relative_humidity_2m_max"][i],
             "wind_max":  d["wind_speed_10m_max"][i],
             "precip":    (d.get("precipitation_sum") or [0]*forecast_days)[i] or 0,
             "national":  national}
            for i in range(len(d.get("time", [])))]


@app.get("/daily/score", tags=["live"])
def daily_score(date: str | None = None):
    """
    Fetch today's weather for all 24 governorates + incident baseline,
    score every governorate, return predictions + HTML report in one call.
    Used as the single HTTP node in the n8n daily workflow.
    """
    target = date or date_cls.today().isoformat()
    national, roll3 = _fetch_incident_baseline(target)
    s = scorer()
    results: list[RiskResult] = []

    with httpx.Client(timeout=15) as client:
        for gov, (lat, lon) in GOVERNORATES.items():
            try:
                wx_rows = _fetch_weather_row(gov, lat, lon, target, client, national)
                if not wx_rows:
                    continue
                w = wx_rows[0]
                row = build_single_row(
                    day=target, governorate=gov,
                    temp_max=w["temp_max"], temp_min=w["temp_min"], temp_mean=w["temp_mean"],
                    rh_max=w["rh_max"], wind_max=w["wind_max"], precip=w["precip"],
                    national_reports_down=national,
                ).to_dict(orient="records")[0]
                row["national_reports_roll3"] = roll3
                results.append(s.score_row(row))
            except Exception as e:
                log.warning("daily_score failed for %s: %s", gov, e)

    predictions = [r.to_dict() for r in results]
    has_high    = any(p["risk_level"] in ("High", "Extreme") for p in predictions)
    return {
        "date": target,
        "national_reports": national,
        "count": len(results),
        "has_high_risk": has_high,
        "predictions": predictions,
        "html": render_national_report(results),
    }


@app.get("/forecast/outage", tags=["live"])
def forecast_outage(days: int = 7):
    """
    7-day electricity outage forecast for all 7 STEG regions.
    Uses the XGBoost model trained on STEG + incident.tn + Open-Meteo data.
    Returns per-day, per-region outage probability + predicted time window.
    """
    from pathlib import Path
    import json as _json

    forecast_path = Path("data/artifacts/outage_forecast_7day.json")
    meta_path     = Path("data/artifacts/outage_model_meta.json")

    if not forecast_path.exists():
        raise HTTPException(
            status_code=503,
            detail="Outage forecast not available. Run: python train_outage_model.py"
        )

    with open(forecast_path, encoding="utf-8") as f:
        forecast = _json.load(f)

    meta = {}
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = _json.load(f)

    # Limit to requested days
    sorted_days = sorted(forecast.keys())[:days]
    result = {d: forecast[d] for d in sorted_days}

    # Summary stats
    all_preds  = [p for day in result.values() for p in day]
    high_risk  = [p for p in all_preds if p["outage_likely"]]

    return {
        "forecast_days":    len(result),
        "trained_at":       meta.get("trained_at", "unknown"),
        "train_accuracy":   meta.get("train_accuracy"),
        "data_sources":     meta.get("data_sources", []),
        "total_predictions": len(all_preds),
        "high_risk_count":  len(high_risk),
        "forecast":         result,
    }


@app.get("/forecast/outage/html", response_class=HTMLResponse, tags=["live"])
def forecast_outage_html(days: int = 7):
    """HTML email-ready outage forecast for all regions."""
    from pathlib import Path
    import json as _json
    from datetime import date as date_cls

    forecast_path = Path("data/artifacts/outage_forecast_7day.json")
    if not forecast_path.exists():
        raise HTTPException(503, "Run python train_outage_model.py first")

    with open(forecast_path, encoding="utf-8") as f:
        forecast = _json.load(f)

    sorted_days = sorted(forecast.keys())[:days]

    rows_html = ""
    for day in sorted_days:
        preds = sorted(forecast[day], key=lambda x: -x["outage_prob"])
        for p in preds:
            if not p["outage_likely"]:
                continue
            pct   = int(p["outage_prob"] * 100)
            color = "#7b1fa2" if pct >= 85 else "#f44336" if pct >= 65 else "#ff9800"
            rows_html += f"""
            <tr>
              <td style='padding:9px 14px'><strong>{day}</strong></td>
              <td style='padding:9px 14px'>{p['region']}</td>
              <td style='padding:9px 14px'>
                <span style='background:{color};color:#fff;padding:2px 10px;border-radius:12px;font-size:0.8rem'>
                  {pct}%
                </span>
              </td>
              <td style='padding:9px 14px'>{p['time_window']}</td>
              <td style='padding:9px 14px'>{p['temp_max']:.0f}°C</td>
            </tr>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/></head>
<body style='font-family:Arial,sans-serif;background:#f4f6f9;padding:20px'>
<div style='max-width:700px;margin:auto'>
  <h2 style='color:#1a1a2e'>⚡ 7-Day Electricity Outage Forecast — Tunisia</h2>
  <p style='color:#666;font-size:0.85rem;margin-bottom:16px'>
    Generated: <strong>{date_cls.today().isoformat()}</strong> &nbsp;·&nbsp;
    Model: XGBoost trained on STEG + incident.tn + Open-Meteo
  </p>
  <table style='width:100%;border-collapse:collapse;background:#fff;border-radius:10px;
                overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)'>
    <thead><tr style='background:#1a1a2e;color:#fff'>
      <th style='padding:10px 14px;text-align:left'>Date</th>
      <th style='padding:10px 14px;text-align:left'>Region</th>
      <th style='padding:10px 14px;text-align:left'>Probability</th>
      <th style='padding:10px 14px;text-align:left'>Time Window</th>
      <th style='padding:10px 14px;text-align:left'>🌡️ Temp</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style='margin-top:16px;font-size:0.75rem;color:#aaa'>
    hack-olive · Tunisia Electricity Risk ·
    Data: STEG scrape + incident.tn + Open-Meteo ERA5
  </p>
</div></body></html>"""

    return HTMLResponse(html)


@app.get("/forecast/governorate", tags=["live"])
def forecast_governorate(governorate: str = "Sfax", days: int = 7):
    """
    7-day outage risk forecast for one governorate.
    Returns per-day predictions + HTML email body.
    """
    coords = GOVERNORATES.get(governorate)
    if not coords:
        raise HTTPException(404, f"Unknown governorate '{governorate}'. "
                                 f"Valid: {sorted(GOVERNORATES.keys())}")
    lat, lon  = coords
    days      = max(1, min(days, 14))
    today_str = date_cls.today().isoformat()
    national, roll3 = _fetch_incident_baseline(today_str)

    s = scorer()
    daily_results: list[dict] = []

    with httpx.Client(timeout=15) as client:
        try:
            wx_rows = _fetch_weather_row(governorate, lat, lon, today_str, client,
                                         national, forecast_days=days)
        except Exception as e:
            raise HTTPException(502, f"Open-Meteo error: {e}")

    for w in wx_rows:
        try:
            row = build_single_row(
                day=w["date"], governorate=governorate,
                temp_max=w["temp_max"], temp_min=w["temp_min"], temp_mean=w["temp_mean"],
                rh_max=w["rh_max"], wind_max=w["wind_max"], precip=w["precip"],
                national_reports_down=national,
            ).to_dict(orient="records")[0]
            row["national_reports_roll3"] = roll3
            daily_results.append(s.score_row(row).to_dict())
        except Exception as e:
            log.warning("Forecast score failed %s: %s", w.get("date"), e)

    peak      = max(daily_results, key=lambda x: x["risk_score"]) if daily_results else None
    high_days = [r for r in daily_results if r["risk_level"] in ("High", "Extreme")]

    alert_banner = ""
    if high_days:
        dates = ", ".join(r["day"] for r in high_days)
        alert_banner = f"<div style='background:#f44336;color:#fff;padding:14px 18px;border-radius:8px;margin-bottom:16px'>🚨 <strong>High/Extreme risk forecast on:</strong> {dates}</div>"

    rows_html = "".join(f"""
    <tr>
      <td style='padding:9px 14px'><strong>{r['day']}</strong></td>
      <td style='padding:9px 14px'>
        <span style='background:{r['risk_color']};color:#fff;padding:2px 10px;border-radius:12px;font-size:0.8rem'>{r['risk_level']}</span>
      </td>
      <td style='padding:9px 14px'>{r['temp_max']}°C</td>
      <td style='padding:9px 14px'>{r['heat_stress']}°C</td>
      <td style='padding:9px 14px'>{r['risk_score']:.3f}</td>
      <td style='padding:9px 14px;font-size:0.78rem;color:#555'>{r['explanation']}</td>
    </tr>""" for r in daily_results)

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/></head>
<body style='font-family:Arial,sans-serif;background:#f4f6f9;padding:20px'>
<div style='max-width:700px;margin:auto'>
  <h2 style='color:#1a1a2e'>⚡ 7-Day Electricity Outage Risk Forecast</h2>
  <p style='color:#666;font-size:0.88rem;margin-bottom:16px'>
    Governorate: <strong>{governorate}</strong> &nbsp;·&nbsp;
    Generated: <strong>{today_str}</strong> &nbsp;·&nbsp;
    Model: <strong>{daily_results[0]['model_version'] if daily_results else 'n/a'}</strong>
  </p>
  {alert_banner}
  <table style='width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)'>
    <thead><tr style='background:#1a1a2e;color:#fff'>
      <th style='padding:10px 14px;text-align:left'>Date</th>
      <th style='padding:10px 14px;text-align:left'>Risk</th>
      <th style='padding:10px 14px;text-align:left'>🌡️ Temp</th>
      <th style='padding:10px 14px;text-align:left'>🥵 Heat Index</th>
      <th style='padding:10px 14px;text-align:left'>Score</th>
      <th style='padding:10px 14px;text-align:left'>Analysis</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style='margin-top:20px;font-size:0.75rem;color:#aaa'>
    hack-olive · Tunisia Electricity Risk · Open-Meteo forecast + incident.tn baseline
  </p>
</div></body></html>"""

    return {
        "governorate":    governorate,
        "forecast_days":  len(daily_results),
        "high_risk_days": [r["day"] for r in high_days],
        "peak_risk_day":  peak["day"] if peak else None,
        "peak_risk_level": peak["risk_level"] if peak else None,
        "daily":          daily_results,
        "html":           html,
    }
