# How hack-olive Works

Tunisia electricity outage risk system — end-to-end guide.

---

## Big Picture

Every day at 06:00 UTC, an automated pipeline:
1. Pulls live weather from Open-Meteo and incident reports from incident.tn
2. Scores each governorate's outage risk (Low / Moderate / High / Extreme)
3. Sends a **daily summary email** regardless of risk level (temperature + report count)
4. Sends an **alert email** only if any governorate hits High or Extreme risk
5. Generates a full HTML report covering all 24 governorates

---

## System Components

```
┌─────────────────────────────────────────────────────────────┐
│                        n8n  :5678                           │
│                                                             │
│  Daily Trigger (06:00 UTC)                                  │
│       │                                                     │
│       ├──► Fetch Weather (Open-Meteo)                       │
│       │         │                                           │
│       │    Fetch Incidents (incident.tn)                    │
│       │         │                                           │
│       │    Build Payload (Code node)                        │
│       │    ┌────┴────────────────────┐                      │
│       │    │                         │                      │
│       │  POST /predict/batch   POST /report/national        │
│       │  POST /predict/batch   Build Daily Summary Email    │
│       │    │                         │                      │
│       │  Any High Risk? ──true──► Send Alert Email          │
│       │       └──false──► No Alert                          │
│       │                         │                           │
│       │                   Send Daily Summary Email          │
└───────┴─────────────────────────────────────────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │  risk-api  :8000  │
         │                  │
         │  FastAPI app      │
         │  risk_model.py    │  ◄── Phase 1: rule-based scorer
         │  calibration.json │       (Phase 2: XGBoost, auto)
         │  generate_report  │
         └──────────────────┘
```

---

## Emails You Receive

### 1. Daily Summary Email (always sent)
Subject: `📊 Daily Report — 2026-08-10 — Temp: 43.2°C`

Contains:
- Maximum temperature for the day (Tunis reference point)
- Total national outage reports from incident.tn
- Date

This arrives every morning regardless of conditions — gives you a baseline pulse.

### 2. Alert Email (only when risk is High or Extreme)
Subject: `⚡ HIGH/EXTREME electricity outage risk — 2026-08-10`

Contains:
- Full HTML report from `/report/national`
- Risk level per governorate, ranked by score
- Temperature, heat stress index, outage report counts
- Explanation of what's driving the risk

---

## Risk Scoring (Phase 1 — Rule-Based)

The risk scorer combines 4 weighted components:

| Component       | Weight | What it measures |
|----------------|--------|-----------------|
| Temperature     | 30%    | Max temperature vs calibrated thresholds |
| Heat Stress     | 25%    | Heat index (apparent temp) — temperature + humidity combined |
| Reports         | 30%    | National outage report volume vs calibrated thresholds |
| Trend           | 15%    | Whether reports are rising vs the 3-day average |

Each component scores 0–1 using a sigmoid curve anchored at the calibrated thresholds. The weighted sum gives the final `risk_score` (0.0–1.0).

**Risk levels:**

| Level    | Score     | Colour  |
|----------|-----------|---------|
| Low      | 0.00–0.24 | 🟢 Green  |
| Moderate | 0.25–0.49 | 🟠 Orange |
| High     | 0.50–0.74 | 🔴 Red    |
| Extreme  | 0.75–1.00 | 🟣 Purple |

### Why rule-based and not ML?

incident.tn launched during the July 2026 heatwave. As of Aug 10, 2026 there are only **18 days of data**. Training XGBoost on 18 data points and calling it a model would be overfitting, not learning. The rules are calibrated from the real 18-day distribution and achieve **Pearson r = 0.904** against actual outage patterns.

### Phase 2 — XGBoost (auto, no code changes needed)

Once the pipeline accumulates ≥ 90 days of data (~late October 2026):
1. Run: `python -m src.model.train` *(to be added)*
2. It saves `data/artifacts/xgb_model.json`
3. Restart the API — it detects the file, loads the model, switches to Phase 2

The same feature columns feed both the rule scorer and XGBoost — no rewrite, just a config flip.

---

## Data Sources

### incident.tn
- **Endpoint:** `GET /api/v1/history?type=electricity&days=90`
- **What it returns:** Per-day, per-governorate electricity outage report counts
- **Coverage:** All 24 Tunisian governorates
- **History:** July 23, 2026 onwards (platform launched during 2026 heatwave)
- **No API key required**

### Open-Meteo
- **Archive endpoint:** `https://archive-api.open-meteo.com/v1/archive`
- **Forecast endpoint:** `https://api.open-meteo.com/v1/forecast`
- **Variables:** `temperature_2m_max/min/mean`, `relative_humidity_2m_max/min`, `wind_speed_10m_max`, `precipitation_sum`, `et0_fao_evapotranspiration`
- **Coverage:** Full ERA5 historical archive back to 1940, gap-free
- **No API key required**

---

## Features Built from Raw Data

The feature engineering (`src/pipeline/features.py`) produces these columns:

| Feature | Description |
|---------|-------------|
| `temp_max/min/mean` | Daily temperature (°C) |
| `temp_range` | Max − Min temperature |
| `rh_max/min/mean` | Relative humidity (%) |
| `heat_stress` | Heat index / apparent temperature (Rothfusz formula) |
| `wind_max` | Max wind speed (km/h) |
| `precip` | Precipitation sum (mm) |
| `day_of_week` | 0=Mon … 6=Sun |
| `month` | 1–12 |
| `is_weekend` | 0 or 1 |
| `reports_down_lag1/2/3` | Per-governorate outage reports 1–3 days ago |
| `reports_down_roll3/7` | Per-governorate rolling average (3 and 7 days) |
| `national_reports_down` | Total reports across all 24 governorates that day |
| `national_reports_roll3` | 3-day national rolling average (lagged) |

---

## File Structure

```
hack-olive/
├── src/
│   ├── pipeline/
│   │   ├── config.py          all constants, API URLs, governorate coords
│   │   ├── download_data.py   fetches incident.tn + Open-Meteo, merges data
│   │   └── features.py        deterministic feature engineering (shared)
│   ├── model/
│   │   ├── calibrate.py       derives thresholds from real data → calibration.json
│   │   ├── risk_model.py      Phase-1 rule scorer + Phase-2 XGBoost gate
│   │   └── evaluate.py        baseline MAE + backtest correlation
│   ├── api/
│   │   ├── app.py             FastAPI: /health /predict /predict/batch /report/*
│   │   └── schemas.py         Pydantic request/response models
│   └── report/
│       ├── generate_report.py Jinja2 HTML renderer
│       └── template.html      report template (single + national views)
├── n8n/
│   └── workflow.json          daily automation (import into n8n UI)
├── docker/
│   ├── Dockerfile             multi-stage Python 3.11 image
│   └── docker-compose.yml     risk-api + n8n services
├── data/
│   ├── raw/                   API JSON responses (gitignored)
│   ├── processed/             merged_dataset.parquet + .csv
│   └── artifacts/             calibration.json, reports, xgb model (future)
├── run_pipeline.py            full pipeline: download → calibrate → evaluate → report
├── verify_data.py             data feasibility check (original validation script)
└── requirements.txt
```

---

## Running It Locally (without Docker)

```bash
# 1. Create and activate venv
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run full data pipeline
python run_pipeline.py
# Downloads live data, calibrates thresholds, evaluates, saves HTML report

# 4. Start the API
uvicorn src.api.app:app --reload --port 8000
# Interactive docs at http://localhost:8000/docs

# 5. Test a prediction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "governorate": "Tunis",
    "day": "2026-08-10",
    "temp_max": 43.2,
    "temp_min": 28.5,
    "temp_mean": 36.0,
    "rh_max": 62,
    "national_reports_down": 9200
  }'
```

---

## Running with Docker

```bash
cd docker
docker compose up --build

# API:  http://localhost:8000
# n8n:  http://localhost:5678  (admin / changeme)
```

Import the workflow:
1. n8n → Workflows → Import from file → select `n8n/workflow.json`
2. Settings → Variables → add `ALERT_EMAIL` = your email
3. Add SMTP credentials in n8n → Credentials → Create → Email (SMTP)
4. Assign the credential to both email nodes
5. Click **Execute workflow** to test

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check + model phase info |
| `GET` | `/model/info` | Thresholds, weights, ml_ready flag |
| `POST` | `/predict` | Single (day, governorate) risk score |
| `POST` | `/predict/batch` | Up to 200 observations at once |
| `POST` | `/report/single` | HTML report for one governorate |
| `POST` | `/report/national` | Combined HTML table for all submitted governorates |

---

## What the Pipeline Output Looks Like

After `python run_pipeline.py`:

```
data/
├── raw/
│   ├── incident_history.json        raw API response (430 rows)
│   ├── incident_analytics.json      analytics summary
│   └── weather_all_governorates.json  18 days × 24 governorates
├── processed/
│   ├── merged_dataset.parquet       432 rows (18 days × 24 govs)
│   └── merged_dataset.csv           same, CSV format
└── artifacts/
    ├── calibration.json             derived thresholds + feature stats
    ├── evaluation_summary.json      baseline MAE, correlation r
    └── national_report_2026-08-09.html  full risk report (open in browser)
```

---

## Calibration Results (Aug 10, 2026)

Derived from 18 real days of data:

| Threshold | Value |
|-----------|-------|
| Temperature — High | ~38°C (60th percentile) |
| Temperature — Extreme | ~43°C (85th percentile) |
| National Reports — High | ~2,000/day |
| National Reports — Extreme | ~6,000/day |

Baseline evaluation:
- Naive yesterday MAE: **2,593** reports/day
- Rolling 3-day MAE: **3,559** reports/day  
- Rule scorer Pearson r: **0.904** (strong correlation with actual outages)

The naive "yesterday" baseline beats the rolling average because the heatwave swings are too sharp for smoothing — exactly what the rule scorer's trend component is designed to catch.
