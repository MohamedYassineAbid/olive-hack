"""
Central configuration — API endpoints, paths, and tuneable constants.
All values can be overridden by environment variables.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_ARTIFACTS = ROOT / "data" / "artifacts"

# ── incident.tn ────────────────────────────────────────────────────────────
INCIDENT_BASE = os.getenv("INCIDENT_BASE", "https://api.incident.tn/api/v1")
INCIDENT_HISTORY_DAYS = int(os.getenv("INCIDENT_HISTORY_DAYS", "90"))

# ── Open-Meteo (no key required) ──────────────────────────────────────────
METEO_ARCHIVE_BASE = os.getenv(
    "METEO_ARCHIVE_BASE",
    "https://archive-api.open-meteo.com/v1/archive",
)
METEO_FORECAST_BASE = os.getenv(
    "METEO_FORECAST_BASE",
    "https://api.open-meteo.com/v1/forecast",
)

# ── Tunisia governorates: name → (lat, lon) ───────────────────────────────
GOVERNORATES: dict[str, tuple[float, float]] = {
    "Ariana":         (36.8625, 10.1956),
    "Beja":           (36.7256, 9.1817),
    "Ben Arous":      (36.7533, 10.2281),
    "Bizerte":        (37.2744, 9.8739),
    "Gabes":          (33.8881, 10.0975),
    "Gafsa":          (34.4311, 8.7757),
    "Jendouba":       (36.5011, 8.7803),
    "Kairouan":       (35.6781, 10.0964),
    "Kasserine":      (35.1722, 8.8306),
    "Kebili":         (33.7044, 8.9694),
    "Kef":            (36.1822, 8.7147),
    "Mahdia":         (35.5047, 11.0622),
    "Manouba":        (36.8094, 10.0969),
    "Medenine":       (33.3550, 10.5050),
    "Monastir":       (35.7643, 10.8113),
    "Nabeul":         (36.4561, 10.7375),
    "Sfax":           (34.7406, 10.7603),
    "Sidi Bouzid":    (35.0381, 9.4858),
    "Siliana":        (36.0844, 9.3708),
    "Sousse":         (35.8256, 10.6084),
    "Tataouine":      (32.9211, 10.4511),
    "Tozeur":         (33.9197, 8.1336),
    "Tunis":          (36.8065, 10.1815),
    "Zaghouan":       (36.4028, 10.1428),
}

# ── Risk thresholds (overridden by calibration artifact when it exists) ────
# These are the hard-coded "cold start" defaults derived from the 18-day
# distribution so the system works on day-0 before calibrate.py is run.
DEFAULT_HIGH_TEMP_C = 38.0      # temp_max above which heat stress is "high"
DEFAULT_EXTREME_TEMP_C = 42.0   # temp_max above which heat stress is "extreme"
DEFAULT_REPORTS_HIGH = 2000     # national daily reports considered "elevated"
DEFAULT_REPORTS_EXTREME = 6000  # national daily reports considered "extreme"

# ── ML readiness gate ─────────────────────────────────────────────────────
# Switch to XGBoost automatically once we cross this many labelled days.
ML_MIN_DAYS = 90
