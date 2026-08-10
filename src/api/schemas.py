"""
Pydantic v2 request/response schemas for the FastAPI prediction service.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── Request schemas ───────────────────────────────────────────────────────

class WeatherInput(BaseModel):
    """Weather + optional incident context for one (day, governorate) pair."""

    governorate: str = Field(..., examples=["Tunis"])
    day: str         = Field(..., examples=["2026-08-10"],
                             description="ISO date YYYY-MM-DD")

    temp_max:  float = Field(..., ge=-10, le=60, examples=[42.5])
    temp_min:  float = Field(..., ge=-10, le=55, examples=[28.1])
    temp_mean: float = Field(..., ge=-10, le=58, examples=[35.3])

    rh_max: float    = Field(..., ge=0, le=100, examples=[65.0],
                             description="Max relative humidity %")
    rh_min: float | None = Field(None, ge=0, le=100,
                                 description="Min relative humidity % (optional)")

    wind_max:  float | None = Field(None, ge=0, examples=[18.0],
                                    description="Max wind speed km/h")
    precip:    float        = Field(0.0, ge=0, examples=[0.0],
                                    description="Precipitation sum mm")
    et0:       float | None = Field(None, ge=0,
                                    description="FAO ET₀ mm (optional)")

    # Optional observed incident context (0 if unknown / future forecast)
    national_reports_down:  int = Field(0, ge=0)
    national_reports_roll3: float = Field(0.0, ge=0)
    reports_down_lag1:      int = Field(0, ge=0)
    reports_down_lag2:      int = Field(0, ge=0)
    reports_down_lag3:      int = Field(0, ge=0)
    reports_down_roll3:     float = Field(0.0, ge=0)
    reports_down_roll7:     float = Field(0.0, ge=0)

    @field_validator("day")
    @classmethod
    def validate_date(cls, v: str) -> str:
        from datetime import date
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"day must be ISO format YYYY-MM-DD, got: {v!r}")
        return v


class BatchPredictRequest(BaseModel):
    observations: list[WeatherInput] = Field(
        ..., min_length=1, max_length=200,
        description="Up to 200 (day, governorate) observations"
    )


# ── Response schemas ──────────────────────────────────────────────────────

class ContributionBreakdown(BaseModel):
    temperature:  float
    heat_stress:  float
    reports:      float
    trend:        float


class PredictionResponse(BaseModel):
    governorate:       str
    day:               str
    risk_level:        str   = Field(..., examples=["High"])
    risk_level_int:    int   = Field(..., ge=0, le=3)
    risk_score:        float = Field(..., ge=0.0, le=1.0)
    temp_max:          float
    heat_stress:       float
    national_reports:  int
    contributions_pct: dict[str, float]
    explanation:       str
    model_version:     str
    risk_color:        str   = Field(..., examples=["#f44336"])


class BatchPredictResponse(BaseModel):
    count:        int
    predictions:  list[PredictionResponse]


class HealthResponse(BaseModel):
    status:        str
    model_phase:   str
    ml_ready:      bool
    n_days:        int
    version:       str


class ModelInfoResponse(BaseModel):
    phase:      str
    ml_ready:   bool
    n_days:     int
    thresholds: dict[str, Any]
    weights:    dict[str, float]
