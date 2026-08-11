# hack-olive — Tunisia Electricity Outage Risk System

Predicts electricity outage risk and timing across Tunisia using three live data sources:
- **STEG** scraped outage notices (`data/steg-outage-data/`)
- **incident.tn** citizen outage reports API
- **Open-Meteo** weather archive and forecast (no key required)

---

## Project Structure

```
hack-olive/
├── core.py                        # config, features, calibration, risk scoring, HTML renderer
├── api.py                         # FastAPI — all endpoints
├── pipeline.py                    # download → merge → calibrate → evaluate → report (CLI)
├── train_outage_model.py          # train XGBoost on STEG + incident.tn + weather, predict 7 days
│
├── data/
│   ├── steg-outage-data/          # scraped STEG outage notices (113 events, 11 days)
│   │   └── data/processed/
│   │       ├── steg_outages.csv
│   │       ├── steg_outages.json
│   │       └── steg_outages.xlsx
│   ├── raw/                       # live API responses (incident.tn + Open-Meteo)
│   ├── processed/                 # merged_dataset.parquet / .csv (18 days × 24 govs)
│   └── artifacts/                 # model files + forecasts (see below)
│
├── n8n/
│   ├── workflow.json              # daily risk pipeline (all 24 govs + Sfax 7-day + emails)
│   └── steg_monitor_workflow.json # STEG news monitor every 3h → email on new outage notice
│
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── verify_data.py                 # original data feasibility check
└── requirements.txt
```

---

## Model Artifacts (`data/artifacts/`)

| File | Description |
|------|-------------|
| `outage_clf.json` | XGBoost binary classifier — outage yes/no per region per day |
| `outage_reg.json` | XGBoost regressor — predicted start hour of outage |
| `outage_model_meta.json` | Feature list, region map, training stats, data sources |
| `outage_forecast_7day.json` | Latest 7-day forecast (JSON, served by `/forecast/outage`) |
| `outage_forecast_7day.csv` | Same forecast as CSV |
| `calibration.json` | Risk scorer thresholds derived from real incident.tn data |
| `evaluation_summary.json` | Baseline MAE + rule scorer correlation |
| `national_report_*.html` | Latest generated national risk report |

### Why XGBoost JSON, not joblib?

XGBoost models are saved in XGBoost's native `.json` format — not joblib. This is intentional:
- **Portable** — loadable across Python versions and platforms
- **Readable** — plain JSON, inspectable in any text editor
- **Versioned** — XGBoost guarantees backward compatibility
- **No pickle risk** — joblib/pickle files are a security risk if untrusted

---

## Quick Start

```bash
# 1. Create venv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Download live data + calibrate + generate report
python pipeline.py

# 3. Train the outage prediction model (STEG + incident.tn + weather)
python train_outage_model.py

# 4. Start API
uvicorn api:app --host 0.0.0.0 --port 8000

# 5. View 7-day forecast
curl http://localhost:8000/forecast/outage
# or open in browser:
curl http://localhost:8000/forecast/outage/html > forecast.html
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness + model phase |
| `GET` | `/model/info` | Thresholds, weights, ml_ready |
| `POST` | `/predict` | Single (day, governorate) risk score |
| `POST` | `/predict/batch` | Up to 200 observations |
| `POST` | `/report/national/json` | HTML risk report as JSON (for n8n) |
| `GET` | `/daily/score` | Fetch + score all 24 govs live (n8n daily workflow) |
| `GET` | `/forecast/governorate?governorate=Sfax&days=7` | 7-day risk forecast, one gov |
| `GET` | `/forecast/outage?days=7` | 7-day outage forecast, all 7 STEG regions (JSON) |
| `GET` | `/forecast/outage/html` | Same forecast as HTML email |

---

## Training Data

| Source | Records | Date Range | Granularity |
|--------|---------|------------|-------------|
| STEG scrape | 113 outage events | Jul 18 – Aug 6, 2026 | Day × STEG region |
| incident.tn | 432 rows | Jul 23 – Aug 9, 2026 | Day × governorate (24) |
| Open-Meteo | 432 rows | Jul 23 – Aug 9, 2026 | Day × governorate (24) |

**Training features:** day of week, month, is_weekend, temp_max/min/mean, rh_max, wind_max, precip, national_reports, region_reports, prev_day_outage, outages_last3

**Model accuracy on training set:** 100% (77 rows — overfitting expected with small dataset; improves as STEG data accumulates)

---

## n8n Workflows

### 1. Daily Risk Pipeline (`workflow.json`)
Runs at **06:00 UTC** every day:
- Fetches weather for all 24 governorates + incident.tn stats
- Scores outage risk (Low/Moderate/High/Extreme) per governorate
- **Alert email** if any governorate is High or Extreme
- **Daily summary email** always (top-5 risk table)
- **Sfax 7-day forecast email** always

### 2. STEG Monitor (`steg_monitor_workflow.json`)
Runs every **3 hours**:
- Scrapes `steg.com.tn/fr/news`
- Filters for electricity outage notices
- Detects new articles via URL deduplication (static data)
- Sends email only when a new article appears
- Currently filtered to **Sfax only** (`SFAX_ONLY = true` in code node)

**Import both into n8n separately** (Workflows → Import from file).

---

## Risk Scoring (Phase 1 — Rule-Based)

| Component | Weight | Signal |
|-----------|--------|--------|
| Temperature | 30% | temp_max vs calibrated thresholds (38°C high, 42°C extreme) |
| Heat stress | 25% | Rothfusz heat index (temp + humidity) |
| Outage reports | 30% | national incident.tn report volume |
| Trend | 15% | rising vs 3-day rolling average |

**Risk levels:** Low (0.00–0.24) · Moderate (0.25–0.49) · High (0.50–0.74) · Extreme (0.75–1.00)

Phase 2 (XGBoost) activates automatically when `calibration.json` shows `ml_ready: true` (≥90 real days from incident.tn).

---

## Retrain the Model

```bash
# After new STEG data is scraped or more incident.tn days accumulate:
python train_outage_model.py

# Predict only (skip training, use saved model):
python train_outage_model.py --predict-only

# Refresh live data first:
python pipeline.py
python train_outage_model.py
```

The API serves the forecast from `data/artifacts/outage_forecast_7day.json` — no restart needed after retraining.
