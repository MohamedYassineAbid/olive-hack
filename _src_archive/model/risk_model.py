"""
Risk scorer — Phase 1: rule-based hybrid.

Architecture
────────────
The scorer is deliberately split into two clearly labelled sections:
  • DOMAIN RULES  — human-interpretable logic that runs always
  • ML GATE       — loads / trains XGBoost and replaces the rules once
                    ml_ready=True in the calibration artifact

Risk levels: LOW (0) · MODERATE (1) · HIGH (2) · EXTREME (3)
Risk score:  0.0 – 1.0  (continuous, for ranking / sorting)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import pandas as pd

from src.model.calibrate import load_artifact

log = logging.getLogger(__name__)

# ── Enums & constants ─────────────────────────────────────────────────────

class RiskLevel(IntEnum):
    LOW      = 0
    MODERATE = 1
    HIGH     = 2
    EXTREME  = 3

    def label(self) -> str:
        return self.name.capitalize()


RISK_COLORS = {
    RiskLevel.LOW:      "#4caf50",
    RiskLevel.MODERATE: "#ff9800",
    RiskLevel.HIGH:     "#f44336",
    RiskLevel.EXTREME:  "#7b1fa2",
}

# Component weights (must sum to 1.0)
W_TEMP        = 0.30
W_HEAT_STRESS = 0.25
W_REPORTS     = 0.30
W_TREND       = 0.15


# ── Output container ──────────────────────────────────────────────────────

@dataclass
class RiskResult:
    governorate: str
    day: str
    risk_level: RiskLevel
    risk_score: float           # 0.0 – 1.0
    temp_max: float
    heat_stress: float
    national_reports: int
    contributions: dict[str, float] = field(default_factory=dict)
    explanation: str = ""
    model_version: str = "rule_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "governorate":       self.governorate,
            "day":               self.day,
            "risk_level":        self.risk_level.label(),
            "risk_level_int":    int(self.risk_level),
            "risk_score":        round(self.risk_score, 4),
            "temp_max":          self.temp_max,
            "heat_stress":       self.heat_stress,
            "national_reports":  self.national_reports,
            "contributions_pct": {k: round(v, 1) for k, v in self.contributions.items()},
            "explanation":       self.explanation,
            "model_version":     self.model_version,
            "risk_color":        RISK_COLORS[self.risk_level],
        }


# ── Scorer ────────────────────────────────────────────────────────────────

class RiskScorer:
    """
    Load-once scorer.  Call `score_row()` for a single prediction or
    `score_dataframe()` for batch.
    """

    def __init__(self) -> None:
        self._artifact = load_artifact()
        self._thr = self._artifact["thresholds"]
        self._ml_ready = self._artifact.get("ml_ready", False)
        self._xgb_model = None

        # ── ML GATE ───────────────────────────────────────────────────────
        if self._ml_ready:
            self._xgb_model = self._try_load_xgb()

        log.info(
            "RiskScorer init  ml_ready=%s  n_days=%s",
            self._ml_ready,
            self._artifact.get("n_days"),
        )

    # ── Public API ────────────────────────────────────────────────────────

    def score_row(self, row: dict[str, Any]) -> RiskResult:
        """Score a single observation dict (as returned by build_single_row)."""
        if self._xgb_model is not None:
            return self._score_xgb(row)
        return self._score_rules(row)

    def score_dataframe(self, df: pd.DataFrame) -> list[RiskResult]:
        return [self.score_row(r) for r in df.to_dict(orient="records")]

    def model_info(self) -> dict[str, Any]:
        return {
            "phase":        "2_xgboost" if self._xgb_model else "1_rule_based",
            "ml_ready":     self._ml_ready,
            "n_days":       self._artifact.get("n_days", 0),
            "thresholds":   self._thr,
            "weights": {
                "temperature":  W_TEMP,
                "heat_stress":  W_HEAT_STRESS,
                "reports":      W_REPORTS,
                "trend":        W_TREND,
            },
        }

    # ── DOMAIN RULES (Phase 1) ────────────────────────────────────────────

    def _score_rules(self, row: dict[str, Any]) -> RiskResult:
        thr = self._thr

        temp_max       = float(row.get("temp_max", 25))
        heat_stress    = float(row.get("heat_stress", temp_max))
        nat_reports    = int(row.get("national_reports_down", row.get("national_reports", 0)))
        roll3          = float(row.get("national_reports_roll3", 0))
        gov_lag1       = float(row.get("reports_down_lag1", 0))

        # Component scores [0, 1]
        s_temp      = _sigmoid_score(temp_max,
                                     thr["temp_high_c"], thr["temp_extreme_c"])
        s_heat      = _sigmoid_score(heat_stress,
                                     thr["heat_stress_high"], thr["heat_stress_extreme"])
        s_reports   = _sigmoid_score(nat_reports,
                                     thr["reports_high"], thr["reports_extreme"])
        # Trend: rising if today's national > yesterday's rolling average
        trend_ratio = (nat_reports / max(roll3, 1)) - 1.0
        s_trend     = min(max(trend_ratio / 3.0, 0.0), 1.0)

        # Weighted sum
        score = (
            W_TEMP        * s_temp  +
            W_HEAT_STRESS * s_heat  +
            W_REPORTS     * s_reports +
            W_TREND       * s_trend
        )
        score = round(min(max(score, 0.0), 1.0), 4)

        # Discrete level
        level = _score_to_level(score)

        # Contributions as % of total weighted score
        total = score if score > 0 else 1e-9
        contributions = {
            "temperature":  round(W_TEMP        * s_temp    / total * 100, 1),
            "heat_stress":  round(W_HEAT_STRESS * s_heat    / total * 100, 1),
            "reports":      round(W_REPORTS     * s_reports / total * 100, 1),
            "trend":        round(W_TREND       * s_trend   / total * 100, 1),
        }

        explanation = _build_explanation(
            level, temp_max, heat_stress, nat_reports, roll3, thr
        )

        return RiskResult(
            governorate      = str(row.get("governorate", "Unknown")),
            day              = str(row.get("day", "")),
            risk_level       = level,
            risk_score       = score,
            temp_max         = temp_max,
            heat_stress      = heat_stress,
            national_reports = nat_reports,
            contributions    = contributions,
            explanation      = explanation,
            model_version    = "rule_v1",
        )

    # ── ML GATE (Phase 2) ─────────────────────────────────────────────────
    # This section intentionally kept separate from domain rules.
    # It becomes active automatically when ml_ready flips to True.

    def _try_load_xgb(self):
        """Attempt to load a pre-trained XGBoost model from artifacts/."""
        from pathlib import Path
        model_path = Path(__file__).parent.parent.parent / "data" / "artifacts" / "xgb_model.json"
        if not model_path.exists():
            log.info("ml_ready=True but no xgb_model.json found — falling back to rules")
            return None
        try:
            import xgboost as xgb
            booster = xgb.Booster()
            booster.load_model(str(model_path))
            log.info("XGBoost model loaded from %s", model_path)
            return booster
        except Exception as exc:
            log.warning("Could not load XGBoost model: %s — falling back to rules", exc)
            return None

    def _score_xgb(self, row: dict[str, Any]) -> RiskResult:
        import numpy as np
        import xgboost as xgb

        FEATURE_COLS = [
            "temp_max", "temp_min", "temp_range", "rh_max", "rh_mean",
            "heat_stress", "wind_max", "precip", "et0",
            "day_of_week", "month", "is_weekend",
            "reports_down_lag1", "reports_down_lag2", "reports_down_lag3",
            "reports_down_roll3", "reports_down_roll7",
            "national_reports_down", "national_reports_roll3",
        ]
        vals = [[float(row.get(c, 0) or 0) for c in FEATURE_COLS]]
        dmat = xgb.DMatrix(np.array(vals), feature_names=FEATURE_COLS)
        score = float(self._xgb_model.predict(dmat)[0])
        score = round(min(max(score, 0.0), 1.0), 4)
        level = _score_to_level(score)

        return RiskResult(
            governorate      = str(row.get("governorate", "Unknown")),
            day              = str(row.get("day", "")),
            risk_level       = level,
            risk_score       = score,
            temp_max         = float(row.get("temp_max", 0)),
            heat_stress      = float(row.get("heat_stress", 0)),
            national_reports = int(row.get("national_reports_down", 0)),
            contributions    = {},
            explanation      = f"XGBoost prediction  score={score:.3f}",
            model_version    = "xgb_v1",
        )


# ── Helpers ───────────────────────────────────────────────────────────────

def _sigmoid_score(value: float, low: float, high: float) -> float:
    """
    Map `value` onto [0, 1] with a soft S-curve anchored at `low` → 0.25
    and `high` → 0.75.  Values below `low` compress toward 0; above `high`
    compress toward 1.
    """
    if high <= low:
        return 1.0 if value >= high else 0.0
    mid  = (low + high) / 2.0
    scale = (high - low) / 2.0
    import math
    return round(1 / (1 + math.exp(-3.0 * (value - mid) / scale)), 4)


def _score_to_level(score: float) -> RiskLevel:
    if score >= 0.75:
        return RiskLevel.EXTREME
    if score >= 0.50:
        return RiskLevel.HIGH
    if score >= 0.25:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def _build_explanation(
    level: RiskLevel,
    temp_max: float,
    heat_stress: float,
    nat_reports: int,
    roll3: float,
    thr: dict,
) -> str:
    parts = []
    if temp_max >= thr["temp_extreme_c"]:
        parts.append(f"extreme temperature ({temp_max:.1f}°C)")
    elif temp_max >= thr["temp_high_c"]:
        parts.append(f"high temperature ({temp_max:.1f}°C)")

    if heat_stress >= thr["heat_stress_extreme"]:
        parts.append(f"extreme heat stress index ({heat_stress:.1f}°C apparent)")
    elif heat_stress >= thr["heat_stress_high"]:
        parts.append(f"elevated heat stress ({heat_stress:.1f}°C apparent)")

    if nat_reports >= thr["reports_extreme"]:
        parts.append(f"very high national outage reports ({nat_reports:,})")
    elif nat_reports >= thr["reports_high"]:
        parts.append(f"elevated outage reports ({nat_reports:,})")

    if roll3 > 0 and nat_reports > roll3 * 1.5:
        parts.append(f"rising trend (vs 3-day avg {roll3:,.0f})")

    if not parts:
        return f"Risk level {level.label()}: conditions within normal range."
    return f"Risk level {level.label()} driven by: {'; '.join(parts)}."
