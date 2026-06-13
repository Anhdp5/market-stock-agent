"""
Main Scheduler
===============
Orchestrates the full daily pipeline and schedules it at 08:00 AM
Vietnam time on trading days (Mon-Fri, non-holiday).

Run modes:
  python main.py                              # Start scheduler daemon (08:00 AM daily)
  python main.py --once                       # Run for today, send email
  python main.py --test                       # Run for today, no email
  python main.py --test --date 2026-06-10     # Run for a specific date, no email
  python main.py --test --from 2026-06-01 --to 2026-06-13   # Run for a date range
  python main.py --once --from 2026-06-01 --to 2026-06-13   # Range + send email per day
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pytz
import schedule

import config
from data_processor.normalizer import _is_trading_day, build_trading_day_spine

# ── Logging ────────────────────────────────────────────────────────────────────
(config.BASE_DIR / "logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            str(config.BASE_DIR / "logs" / "agent.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("scheduler")


# ─────────────────────────────────────────────────────────────────────────────
# Core pipeline (single date)
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    dry_run:    bool          = False,
    run_date:   Optional[date] = None,
    force:      bool          = False,
) -> Optional[Path]:
    """
    Run the full intelligence pipeline for a single date.

    Parameters
    ----------
    dry_run   : Skip sending email (save report to disk only).
    run_date  : Date to generate the report for. Defaults to today.
    force     : If True, run even if run_date is not a trading day
                (useful for testing on weekends).
    """
    run_date = run_date or date.today()

    if not force and not _is_trading_day(run_date):
        logger.info(f"{run_date} is not a trading day. Use --force to override.")
        return None

    logger.info("=" * 60)
    logger.info(f"PIPELINE START — {run_date}")
    logger.info("=" * 60)

    # ── Step 1: Market data ───────────────────────────────────────────────────
    logger.info("Step 1/7: Collecting market data (CafeF/vnstock)")
    from collector.market_scraper.cafef_scraper import collect_market_data
    market_df = collect_market_data(end_date=run_date)

    # ── Step 2: ZLP email data ────────────────────────────────────────────────
    logger.info("Step 2/7: Reading Outlook emails (DNSE Metabase)")
    from collector.email_ingestion.email_parser import collect_zlp_data
    try:
        zlp_data = collect_zlp_data(since_days=config.LOOKBACK_DAYS + 5)
    except Exception as e:
        logger.warning(f"Email ingestion failed: {e}. Continuing with market data only.")
        zlp_data = {}

    # ── Step 3: Normalise + store ─────────────────────────────────────────────
    logger.info("Step 3/7: Normalising and storing data")
    from data_processor.normalizer import normalise
    from data_processor.db_manager import DBManager

    unified_df = normalise(market_df, zlp_data, end_date=run_date)
    db = DBManager()
    db.upsert_rows(unified_df)

    # ── Step 4: Analytics — use data up to run_date ───────────────────────────
    logger.info("Step 4/7: Running analytics")
    from analytics_engine.calculator import run_analysis
    from analytics_engine.benchmarker import build_benchmark_table

    run_date_str = run_date.strftime("%Y-%m-%d")
    start_str    = (run_date - timedelta(days=config.LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    analysis_df  = db.read_range(start_str, run_date_str)

    if analysis_df.empty:
        logger.error("No data in DB for the requested date range.")
        return None

    analysis    = run_analysis(analysis_df)
    bench_table = build_benchmark_table(analysis)

    # ── Step 5: Insights + recommendations ────────────────────────────────────
    logger.info("Step 5/7: Generating insights and recommendations")
    from insight_generator.insights import generate_insights, generate_recommendations

    insights        = generate_insights(analysis, bench_table)
    recommendations = generate_recommendations(analysis, bench_table)

    # ── Step 6: Build report ──────────────────────────────────────────────────
    logger.info("Step 6/7: Building report")
    from report_writer.report_builder import (
        build_html_report, build_plain_text_summary, save_report
    )

    html_content = build_html_report(
        report_date=run_date,
        analysis=analysis,
        bench_table=bench_table,
        insights=insights,
        recommendations=recommendations,
    )
    plain_text = build_plain_text_summary(
        report_date=run_date,
        analysis=analysis,
        bench_table=bench_table,
        insights=insights,
        recommendations=recommendations,
    )
    html_path = save_report(html_content, run_date)

    # ── Step 7: Send email ────────────────────────────────────────────────────
    if dry_run:
        logger.info(f"Step 7/7: [DRY RUN] Email skipped. Report: {html_path}")
    else:
        logger.info("Step 7/7: Sending report email")
        from scheduler.mailer import send_report
        send_report(
            html_content=html_content,
            plain_text=plain_text,
            report_date=run_date,
            html_path=html_path,
        )

    logger.info(f"PIPELINE COMPLETE — {run_date}")
    logger.info("=" * 60)
    return html_path


# ─────────────────────────────────────────────────────────────────────────────
# Date range runner
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline_range(
    start_date: date,
    end_date:   date,
    dry_run:    bool = True,
    force:      bool = False,
) -> List[Path]:
    """
    Run the pipeline for every trading day in [start_date, end_date].
    Returns list of saved report paths.
    """
    spine  = build_trading_day_spine(start_date, end_date)
    days   = list(spine["date"])
    paths  = []

    if not days:
        logger.warning(f"No trading days found between {start_date} and {end_date}")
        return []

    logger.info(
        f"Running pipeline for {len(days)} trading day(s): "
        f"{days[0]} → {days[-1]}"
    )

    for i, run_date in enumerate(days, 1):
        logger.info(f"\n[{i}/{len(days)}] Processing {run_date}")
        path = run_p