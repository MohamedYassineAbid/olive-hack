"""
FastAPI prediction service.

Endpoints
─────────
GET  /health                  liveness + model info
GET  /model/info              detailed scorer configuration
POST /predict                 single (day, governorate) prediction
POST /predict/batch           up to 200 observations
POST /report/single           HTML risk report for one governorate
POST /report/national         combined HTML report for all 24 governorates

Run locally:
    uvicorn src.api.app:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from src.api.schemas import (
    BatchPredictRequest,
    BatchPredictResponse,
    HealthResponse,
    ModelInfoResponse,
    PredictionResponse,
    WeatherInput,
)
from src.model.risk_model import RiskScorer
from src.pipeline.features import build_single_row

log = logging.getLogger(__name__)

APP_VERSION = "1.0.0"

# ── Shared scorer instance (loaded once at startup) ───────────────────────
_scorer: RiskScorer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scorer
    log.info("Loading risk scorer …")
    _scorer = RiskScorer()
    log.info("Risk scorer ready  phase=%s", _scorer.model_info()["phase"])
    yield
    _scorer = None


app = FastAPI(
    title="Electricity Outage Risk API",
    description=(
        "Predicts electricity outage risk across Tunisia's 24 governorates "
        "using weather and incident.tn data. Phase 1: rule-based hybrid. "
        "Phase 2: XGBoost (auto-activated at ≥90 days of history)."
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_scorer() -> RiskScorer:
    if _scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialised")
    return _scorer


def _input_to_row(obs: WeatherInput) -> dict[str, Any]:
    df = build_single_row(
        day=obs.day,
        governorate=obs.governorate,
        temp_max=obs.temp_max,
        temp_min=obs.temp_min,
        temp_mean=obs.temp_mean,
        rh_max=obs.rh_max,
        rh_min=obs.rh_min,
        wind_max=obs.wind_max,
        precip=obs.precip,
        et0=obs.et0,
        national_reports_down=obs.national_reports_down,
    )
    # Override lag/rolling fields with caller-supplied values
    row = df.to_dict(orient="records")[0]
    row["national_reports_roll3"] = obs.national_reports_roll3
    row["reports_down_lag1"]      = obs.reports_down_lag1
    row["reports_down_lag2"]      = obs.reports_down_lag2
    row["reports_down_lag3"]      = obs.reports_down_lag3
    row["reports_down_roll3"]     = obs.reports_down_roll3
    row["reports_down_roll7"]     = obs.reports_down_roll7
    return row


# ── Routes ────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health():
    scorer = _get_scorer()
    info   = scorer.model_info()
    return HealthResponse(
        status      = "ok",
        model_phase = info["phase"],
        ml_ready    = info["ml_ready"],
        n_days      = info["n_days"],
        version     = APP_VERSION,
    )


@app.get("/model/info", response_model=ModelInfoResponse, tags=["meta"])
def model_info():
    return ModelInfoResponse(**_get_scorer().model_info())


@app.post("/predict", response_model=PredictionResponse, tags=["prediction"])
def predict(obs: WeatherInput):
    """Score a single (day, governorate) observation."""
    row    = _input_to_row(obs)
    result = _get_scorer().score_row(row)
    return PredictionResponse(**result.to_dict())


@app.post(
    "/predict/batch",
    response_model=BatchPredictResponse,
    tags=["prediction"],
)
def predict_batch(body: BatchPredictRequest):
    """Score up to 200 observations in one call."""
    scorer = _get_scorer()
    preds  = []
    for obs in body.observations:
        row    = _input_to_row(obs)
        result = scorer.score_row(row)
        preds.append(PredictionResponse(**result.to_dict()))
    return BatchPredictResponse(count=len(preds), predictions=preds)


@app.post("/report/single", response_class=HTMLResponse, tags=["report"])
def report_single(obs: WeatherInput):
    """Return a rendered HTML risk report for one governorate."""
    from src.report.generate_report import render_single_report
    row    = _input_to_row(obs)
    result = _get_scorer().score_row(row)
    html   = render_single_report(result)
    return HTMLResponse(content=html)


@app.post("/report/national", response_class=HTMLResponse, tags=["report"])
def report_national(body: BatchPredictRequest):
    """Return a combined HTML report covering all submitted governorates."""
    from src.report.generate_report import render_national_report
    scorer  = _get_scorer()
    results = []
    for obs in body.observations:
        row    = _input_to_row(obs)
        results.append(scorer.score_row(row))
    html = render_national_report(results)
    return HTMLResponse(content=html)


@app.post("/report/national/json", tags=["report"])
def report_national_json(body: BatchPredictRequest):
    """
    Same as /report/national but returns JSON with the HTML inside.
    Use this from n8n so the HTML is reliably accessible as $json.html.
    """
    from src.report.generate_report import render_national_report
    scorer  = _get_scorer()
    results = []
    for obs in body.observations:
        row    = _input_to_row(obs)
        results.append(scorer.score_row(row))
    html = render_national_report(results)
    return {"html": html, "count": len(results)}


@app.get("/forecast/governorate", tags=["prediction"])
def forecast_governorate(governorate: str = "Sfax", days: int = 7):
    """
    7-day outage risk forecast for a single governorate.

    Pulls Open-Meteo forecast weather for the next `days` days,
    scores each day with the risk model, and returns a day-by-day
    risk outlook plus an HTML email-ready summary.

    Query params:
        governorate  Name matching config.GOVERNORATES (default: Sfax)
        days         Forecast horizon 1–14 (default: 7)
    """
    import httpx
    from datetime import date as date_cls, timedelta
    from src.pipeline.config import GOVERNORATES, METEO_FORECAST_BASE, INCIDENT_BASE
    from src.pipeline.features import build_single_row

    coords = GOVERNORATES.get(governorate)
    if not coords:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown governorate '{governorate}'. "
                   f"Valid: {sorted(GOVERNORATES.keys())}"
        )
    lat, lon = coords
    days = max(1, min(days, 14))

    # ── Fetch incident baseline (last 7 days for rolling context) ─────
    national_reports = 0
    roll3 = 0.0
    try:
        with httpx.Client(timeout=15) as client:
            inc = client.get(
                f"{INCIDENT_BASE}/history",
                params={"type": "electricity", "days": 7}
            ).json()
        rows = inc.get("data", {}).get("rows", [])
        national_reports = sum(r.get("reports_down", 0) for r in rows
                               if r.get("day") == date_cls.today().isoformat())
        days3 = sorted({r["day"] for r in rows})[-3:]
        roll3_rows = [r for r in rows if r.get("day") in days3]
        roll3 = sum(r.get("reports_down", 0) for r in roll3_rows) / max(len(days3) * 24, 1)
    except Exception as exc:
        log.warning("Could not fetch incident baseline: %s", exc)

    # ── Fetch 7-day forecast from Open-Meteo ─────────────────────────
    try:
        with httpx.Client(timeout=15) as client:
            wx = client.get(
                METEO_FORECAST_BASE,
                params={
                    "latitude":      lat,
                    "longitude":     lon,
                    "daily": ",".join([
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "temperature_2m_mean",
                        "relative_humidity_2m_max",
                        "wind_speed_10m_max",
                        "precipitation_sum",
                    ]),
                    "forecast_days": days,
                    "timezone":      "Africa/Tunis",
                }
            ).json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Open-Meteo error: {exc}")

    d = wx.get("daily", {})
    dates = d.get("time", [])

    # ── Score each forecast day ───────────────────────────────────────
    scorer = _get_scorer()
    daily_results = []

    for i, forecast_date in enumerate(dates):
        try:
            row = build_single_row(
                day=forecast_date,
                governorate=governorate,
                temp_max=d["temperature_2m_max"][i],
                temp_min=d["temperature_2m_min"][i],
                temp_mean=d["temperature_2m_mean"][i],
                rh_max=d["relative_humidity_2m_max"][i],
                wind_max=d["wind_speed_10m_max"][i],
                precip=d.get("precipitation_sum", [0] * days)[i] or 0,
                national_reports_down=national_reports,
            ).to_dict(orient="records")[0]
            row["national_reports_roll3"] = roll3
            result = scorer.score_row(row)
            daily_results.append(result.to_dict())
        except Exception as exc:
            log.warning("Score failed for %s on %s: %s", governorate, forecast_date, exc)

    # ── Build HTML forecast email ─────────────────────────────────────
    peak = max(daily_results, key=lambda x: x["risk_score"]) if daily_results else None
    high_days = [r for r in daily_results if r["risk_level"] in ("High", "Extreme")]

    rows_html = ""
    for r in daily_results:
        rows_html += f"""
        <tr>
          <td style='padding:9px 14px'><strong>{r['day']}</strong></td>
          <td style='padding:9px 14px'>
            <span style='background:{r['risk_color']};color:#fff;padding:2px 10px;border-radius:12px;font-size:0.8rem'>
              {r['risk_level']}
            </span>
          </td>
          <td style='padding:9px 14px'>{r['temp_max']}°C</td>
          <td style='padding:9px 14px'>{r['heat_stress']}°C</td>
          <td style='padding:9px 14px'>{r['risk_score']:.3f}</td>
          <td style='padding:9px 14px;font-size:0.78rem;color:#555'>{r['explanation']}</td>
        </tr>"""

    alert_banner = ""
    if high_days:
        alert_dates = ", ".join(r["day"] for r in high_days)
        alert_banner = f"""
        <div style='background:#f44336;color:#fff;padding:14px 18px;border-radius:8px;margin-bottom:16px'>
          🚨 <strong>High/Extreme risk forecast on:</strong> {alert_dates}
        </div>"""

    html = f"""
    <!DOCTYPE html>
    <html><head><meta charset="UTF-8"/></head>
    <body style='font-family:Arial,sans-serif;background:#f4f6f9;padding:20px'>
    <div style='max-width:700px;margin:auto'>
      <h2 style='color:#1a1a2e'>⚡ 7-Day Electricity Outage Risk Forecast</h2>
      <p style='color:#666;font-size:0.88rem;margin-bottom:16px'>
        Governorate: <strong>{governorate}</strong> &nbsp;·&nbsp;
        Generated: <strong>{date_cls.today().isoformat()}</strong> &nbsp;·&nbsp;
        Model: <strong>{daily_results[0]['model_version'] if daily_results else 'n/a'}</strong>
      </p>

      {alert_banner}

      <table style='width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)'>
        <thead>
          <tr style='background:#1a1a2e;color:#fff'>
            <th style='padding:10px 14px;text-align:left'>Date</th>
            <th style='padding:10px 14px;text-align:left'>Risk Level</th>
            <th style='padding:10px 14px;text-align:left'>🌡️ Temp Max</th>
            <th style='padding:10px 14px;text-align:left'>🥵 Heat Index</th>
            <th style='padding:10px 14px;text-align:left'>Score</th>
            <th style='padding:10px 14px;text-align:left'>Analysis</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>

      <p style='margin-top:20px;font-size:0.75rem;color:#aaa'>
        hack-olive · Tunisia Electricity Risk System ·
        Weather: Open-Meteo forecast · Incident baseline: incident.tn
      </p>
    </div>
    </body></html>"""

    return {
        "governorate":   governorate,
        "forecast_days": len(daily_results),
        "high_risk_days": [r["day"] for r in high_days],
        "peak_risk_day":  peak["day"] if peak else None,
        "peak_risk_level": peak["risk_level"] if peak else None,
        "daily":         daily_results,
        "html":          html,
    }


@app.get("/daily/score", tags=["prediction"])
def daily_score(date: str | None = None):
    """
    Fetch today's (or any date's) weather for all 24 governorates from
    Open-Meteo, pull incident stats from incident.tn, score every
    governorate, and return the full national risk picture in one call.

    n8n can call this single endpoint instead of wiring 24 HTTP nodes.

    Query param:
        date  ISO date string YYYY-MM-DD (default: today)
    """
    import httpx
    from datetime import date as date_cls
    from src.pipeline.config import GOVERNORATES, METEO_FORECAST_BASE, INCIDENT_BASE
    from src.pipeline.features import build_single_row
    from src.report.generate_report import render_national_report

    target_date = date or date_cls.today().isoformat()

    # ── Fetch incident stats (last 7 days) ────────────────────────────
    national_reports = 0
    roll3 = 0.0
    try:
        with httpx.Client(timeout=15) as client:
            inc = client.get(
                f"{INCIDENT_BASE}/history",
                params={"type": "electricity", "days": 7}
            ).json()
        rows = inc.get("data", {}).get("rows", [])
        today_rows = [r for r in rows if r.get("day") == target_date]
        national_reports = sum(r.get("reports_down", 0) for r in today_rows)
        days3 = sorted({r["day"] for r in rows})[-3:]
        roll3_rows = [r for r in rows if r.get("day") in days3]
        roll3 = sum(r.get("reports_down", 0) for r in roll3_rows) / max(len(days3) * 24, 1)
    except Exception as exc:
        log.warning("Could not fetch incident data: %s", exc)

    # ── Score each governorate ────────────────────────────────────────
    scorer  = _get_scorer()
    results = []

    with httpx.Client(timeout=15) as client:
        for gov, (lat, lon) in GOVERNORATES.items():
            try:
                wx = client.get(
                    METEO_FORECAST_BASE,
                    params={
                        "latitude":      lat,
                        "longitude":     lon,
                        "daily":         "temperature_2m_max,temperature_2m_min,temperature_2m_mean,relative_humidity_2m_max,wind_speed_10m_max,precipitation_sum",
                        "forecast_days": 1,
                        "timezone":      "Africa/Tunis",
                    }
                ).json()
                d = wx.get("daily", {})
                row = build_single_row(
                    day=target_date,
                    governorate=gov,
                    temp_max=d["temperature_2m_max"][0],
                    temp_min=d["temperature_2m_min"][0],
                    temp_mean=d["temperature_2m_mean"][0],
                    rh_max=d["relative_humidity_2m_max"][0],
                    wind_max=d["wind_speed_10m_max"][0],
                    precip=d.get("precipitation_sum", [0])[0] or 0,
                    national_reports_down=national_reports,
                ).to_dict(orient="records")[0]
                row["national_reports_roll3"] = roll3
            except Exception as exc:
                log.warning("Weather fetch failed for %s: %s", gov, exc)
                continue
            results.append(scorer.score_row(row))

    html = render_national_report(results)
    predictions = [r.to_dict() for r in results]
    has_high = any(p["risk_level"] in ("High", "Extreme") for p in predictions)

    return {
        "date":              target_date,
        "national_reports":  national_reports,
        "count":             len(results),
        "has_high_risk":     has_high,
        "predictions":       predictions,
        "html":              html,
    }
