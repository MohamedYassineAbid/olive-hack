# hack-olive — Tunisia Electricity Outage Risk System

Predicts electricity outage risk across Tunisia's 24 governorates by combining
live incident data from [incident.tn](https://incident.tn) with historical and
forecast weather from [Open-Meteo](https://open-meteo.com).

---

## Architecture

```
incident.tn /history  ──┐
incident.tn /analytics  ├──► download_data.py ──► merged_dataset
Open-Meteo archive      ──┘
                                    │
                             features.py  (shared feature engineering)
                                    │
                             calibrate.py (derive thresholds → calibration.json)
                                    │
                             risk_model.py
                             ┌──────┴──────┐
                     Phase 1 │             │ Phase 2 (auto, ≥90 days)
                   Rule-based │             │ XGBoost
                    hybrid    │             │ (config flip, no rewrite)
                                    │
                            FastAPI  :8000
                         /predict  /predict/batch
                         /report/single  /report/national
                                    │
                              n8n workflow
                        (daily 06:00 UTC, email alerts)
```

**Data status (Aug 2026):** 18 real days (Jul 23 – Aug 9).  
Phase 1 (rule-based) is active. Phase 2 flips automatically once `n_days >= 90`.

---

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# 1. Download live data + run full pipeline
python run_pipeline.py

# 2. Start the API
uvicorn src.api.app:app --reload --port 8000

# 3. Single prediction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "governorate": "Tunis",
    "day": "2026-08-10",
    "temp_max": 42.5,
    "temp_min": 28.1,
    "temp_mean": 35.3,
    "rh_max": 65,
    "national_reports_down": 8500
  }'

# 4. National HTML report (open in browser)
curl -X POST http://localhost:8000/report/national \
  -H "Content-Type: application/json" \
  -d @examples/batch_request.json > report.html
```

---

## Docker

```bash
cd docker
docker compose up --build
```

- API: http://localhost:8000
- n8n: http://localhost:5678  (admin / changeme)

Import `n8n/workflow.json` via n8n → Workflows → Import.

---

## Project layout

```
hack-olive/
├── src/
│   ├── pipeline/
│   │   ├── config.py          # all constants + paths
│   │   ├── download_data.py   # incident.tn + Open-Meteo fetcher
│   │   └── features.py        # shared feature engineering
│   ├── model/
│   │   ├── calibrate.py       # threshold derivation → calibration.json
│   │   ├── risk_model.py      # Phase-1 rule scorer + Phase-2 XGBoost gate
│   │   └── evaluate.py        # baselines + backtest
│   ├── api/
│   │   ├── app.py             # FastAPI application
│   │   └── schemas.py         # Pydantic request/response models
│   └── report/
│       ├── generate_report.py # Jinja2 HTML renderer
│       └── template.html      # report template
├── n8n/
│   └── workflow.json          # daily automation workflow
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── data/
│   ├── raw/                   # API JSON responses
│   ├── processed/             # merged_dataset.parquet / .csv
│   └── artifacts/             # calibration.json, reports, xgb model
├── run_pipeline.py            # full pipeline runner
├── verify_data.py             # data feasibility check (original)
└── requirements.txt
```

---

## Phase 2 — XGBoost upgrade path

No code changes needed. Once `data/artifacts/calibration.json` shows
`"ml_ready": true` (happens automatically when the pipeline sees ≥ 90 days):

1. Train a model and save it as `data/artifacts/xgb_model.json`
2. Restart the API — it loads the model and switches phases automatically

The same feature columns used by the rule scorer feed directly into XGBoost.

---

## Risk levels

| Level    | Score range | Colour   |
|----------|-------------|----------|
| Low      | 0.00 – 0.24 | 🟢 Green |
| Moderate | 0.25 – 0.49 | 🟠 Orange |
| High     | 0.50 – 0.74 | 🔴 Red   |
| Extreme  | 0.75 – 1.00 | 🟣 Purple |
