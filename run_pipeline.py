"""
Full pipeline runner — download → calibrate → evaluate → save report.

Usage:
    python run_pipeline.py              # uses default 90-day window
    python run_pipeline.py --days 30    # shorter window for testing
    python run_pipeline.py --skip-download   # re-use existing raw data
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full risk pipeline")
    parser.add_argument("--days", type=int, default=90,
                        help="Days of history to request (default 90)")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip download step and use existing processed data")
    args = parser.parse_args()

    # 1. Download & merge
    if not args.skip_download:
        log.info("═══ Step 1/4  Download & merge data ═══")
        from src.pipeline.download_data import run as download_run
        download_run(args.days)
    else:
        log.info("═══ Step 1/4  Skipped (--skip-download) ═══")

    # 2. Calibrate thresholds
    log.info("═══ Step 2/4  Calibrate risk thresholds ═══")
    from src.model.calibrate import calibrate
    artifact = calibrate()
    log.info("  n_days=%d  ml_ready=%s", artifact["n_days"], artifact["ml_ready"])

    # 3. Evaluate baselines
    log.info("═══ Step 3/4  Evaluate baselines ═══")
    from src.model.evaluate import run_evaluation
    summary = run_evaluation()
    if summary:
        log.info("  Naive yesterday MAE: %.1f", summary["baseline_mae"]["naive_yesterday"])
        log.info("  Rule scorer r:       %s", summary.get("rule_scorer_correlation_r"))

    # 4. Generate national report for latest date in data
    log.info("═══ Step 4/4  Generate national HTML report ═══")
    _generate_latest_report()

    log.info("Pipeline complete. Artifacts in data/artifacts/")
    return 0


def _generate_latest_report() -> None:
    from src.pipeline.config import DATA_PROCESSED, DATA_ARTIFACTS
    import pandas as pd

    pq  = DATA_PROCESSED / "merged_dataset.parquet"
    csv = DATA_PROCESSED / "merged_dataset.csv"
    if pq.exists():
        df = pd.read_parquet(pq)
    elif csv.exists():
        df = pd.read_csv(csv)
    else:
        log.warning("No processed data for report generation")
        return

    from src.pipeline.features import build_features
    feat = build_features(df)
    latest_day = feat["day"].max()
    latest = feat[feat["day"] == latest_day]

    from src.model.risk_model import RiskScorer
    from src.report.generate_report import render_national_report, save_report

    scorer  = RiskScorer()
    results = scorer.score_dataframe(latest)
    html    = render_national_report(results)
    path    = save_report(html, name=f"national_report_{latest_day}")
    log.info("  Report saved → %s", path)


if __name__ == "__main__":
    sys.exit(main())
