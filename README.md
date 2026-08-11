# hack-olive — Tunisia Electricity Outage Risk System

Predicts electricity outage risk and timing across Tunisia using three live data sources:
**STEG** scraped notices · **incident.tn** citizen reports · **Open-Meteo** weather

---

## Files

```
hack-olive/
├── core.py                     config, features, calibration, risk scoring, HTML renderer
├── api.py                      FastAPI — all endpoints
├── pipeline.py                 download → merge → calibrate → evaluate (CLI)
├── train_outage_model.py       train XGBoost on all data, predict 7 days
│
├── data/
│   ├── steg-outage-data/       scraped STEG outage notices (113 events)
│   ├── raw/                    live API JSON responses
│   ├── processed/              merged_dataset.parquet / .csv
│   └── artifacts/              models + forecasts (see below)
│
├── n8n/
│   ├── workflow.json           daily risk pipeline (4 emails)
│   └── steg_monitor_workflow.json  STEG monitor every 3h + MLOps retrain
│
├── docker/
│   ├── Dockerfile              multi-stage Python 3.11 image
│   └── docker-compose.yml      risk-api + n8n
│
├── DOCUMENTATION_FR.md         2-page French technical documentation
├── email_prediction_coupures.html  HTML email template (static preview)
└── requirements.txt
```

---

## Model Artifacts (`data/artifacts/`)

| File | Description |
|------|-------------|
| `outage_clf.json` | XGBoost classifier — outage probability per region per day |
| `outage_reg.json` | XGBoost regressor — predicted start hour |
| `outage_model_meta.json` | Features, region map, training stats, data sources |
| `outage_forecast_7day.json` | Latest 7-day forecast served by `/forecast/outage` |
| `outage_forecast_7day.csv` | Same as CSV |
| `calibration.json` | Risk scorer thresholds from real incident.tn data |
| `evaluation_summary.json` | Baseline MAE + rule scorer correlation |

**Why XGBoost JSON, not joblib?** Portable across Python versions, human-readable, no pickle security risk.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness + model phase |
| `GET` | `/model/info` | Thresholds, weights, ml_ready flag |
| `POST` | `/predict` | Single (day, governorate) risk score |
| `POST` | `/predict/batch` | Up to 200 observations |
| `POST` | `/report/national/json` | HTML risk report as JSON (n8n email) |
| `GET` | `/daily/score` | Fetch + score all 24 govs live |
| `GET` | `/forecast/governorate?governorate=Sfax&days=7` | 7-day weather-based risk forecast |
| `GET` | `/forecast/outage?days=7` | 7-day ML outage forecast, all STEG regions |
| `GET` | `/forecast/outage/html` | Same as HTML email |
| `POST` | `/steg/save-article` | Save new STEG article + check retrain threshold |
| `POST` | `/model/retrain` | Trigger full retrain (called automatically by n8n) |

---

## MLOps — Automatic Retraining

Every time a new STEG article is detected by the monitor workflow:
1. Article saved to `data/steg-outage-data/data/processed/steg_live.csv`
2. `/steg/save-article` returns `should_retrain: true` when total rows crosses a multiple of 30
3. n8n calls `POST /model/retrain` automatically
4. API reruns `pipeline.py` + `train_outage_model.py` and reloads the scorer in-memory
5. New model serves immediately — no restart needed

---

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python pipeline.py               # download data + calibrate
python train_outage_model.py     # train + generate 7-day forecast
uvicorn api:app --host 0.0.0.0 --port 8000
```

**Docker:**
```bash
cd docker && docker compose up --build -d
# API  → http://localhost:8000/docs
# n8n  → http://localhost:5678  (admin / changeme)
```

Import both workflow files in n8n → Workflows → Import from file.

---

## Risk Levels

| Level | Score | Colour |
|-------|-------|--------|
| Low | 0.00–0.24 | 🟢 Green |
| Moderate | 0.25–0.49 | 🟠 Orange |
| High | 0.50–0.74 | 🔴 Red |
| Extreme | 0.75–1.00 | 🟣 Purple |

Phase 2 (XGBoost risk scorer) activates automatically when `calibration.json` shows `ml_ready: true` (≥90 real days from incident.tn).
