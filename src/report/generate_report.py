"""
HTML report generator.

Renders Jinja2 templates from RiskResult objects.
Two entry points:
  render_single_report(result)  → HTML string for one governorate
  render_national_report(results) → HTML string for all governorates
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Sequence

from jinja2 import Environment, FileSystemLoader

from src.model.risk_model import RiskLevel, RiskResult

TEMPLATE_DIR = Path(__file__).parent
_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)


_RISK_EMOJI = {
    RiskLevel.LOW:      "✅",
    RiskLevel.MODERATE: "⚠️",
    RiskLevel.HIGH:     "🔴",
    RiskLevel.EXTREME:  "🚨",
}


def render_single_report(result: RiskResult) -> str:
    """Render a full HTML report for a single governorate prediction."""
    template = _env.get_template("template.html")
    d = result.to_dict()
    return template.render(
        single_gov    = True,
        report_date   = result.day or date.today().isoformat(),
        model_version = result.model_version,
        governorate   = result.governorate,
        risk_level    = d["risk_level"],
        risk_score    = d["risk_score"],
        risk_color    = d["risk_color"],
        risk_emoji    = _RISK_EMOJI[result.risk_level],
        temp_max      = result.temp_max,
        heat_stress   = result.heat_stress,
        national_reports = result.national_reports,
        contributions = d["contributions_pct"],
        explanation   = result.explanation,
    )


def render_national_report(results: Sequence[RiskResult]) -> str:
    """
    Render a combined HTML table report sorted by descending risk score.
    """
    template = _env.get_template("template.html")

    rows = sorted(
        [r.to_dict() for r in results],
        key=lambda x: x["risk_score"],
        reverse=True,
    )

    report_date   = results[0].day if results else date.today().isoformat()
    model_version = results[0].model_version if results else "rule_v1"

    return template.render(
        single_gov    = False,
        report_date   = report_date,
        model_version = model_version,
        rows          = rows,
    )


def save_report(html: str, name: str = "report") -> Path:
    """Save HTML to data/artifacts/<name>.html and return the path."""
    from src.pipeline.config import DATA_ARTIFACTS
    DATA_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = DATA_ARTIFACTS / f"{name}.html"
    path.write_text(html, encoding="utf-8")
    return path
