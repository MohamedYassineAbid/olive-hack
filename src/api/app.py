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
