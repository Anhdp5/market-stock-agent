"""
Main Scheduler
===============
Orchestrates the full daily pipeline and schedules it at 08:00 AM
Vietnam time on trading days (Mon–Fri, non-holiday).

Run modes:
  python scheduler/main_scheduler.py          → Start scheduler daemon
  python scheduler/main_scheduler.py --once   → Run pipeline once immediately
  python scheduler/main_scheduler.py --test   → Dry run (no email sent)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import argparse
import logging
import time
from datetime import date, datetime

import pytz
import schedule

import config
from data_processor.normalizer import _is_trading_day

# Set up logging
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
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(dry_run: bool = False):
    """
    Full daily pipeline:
    1. Pull CafeF market data
    2. Read Outlook emails → extract ZLP metrics
    3. Normalise + upsert to SQLite
    4. Run analytics
    5. Generate insights + recommendations
    6. Build report
    7. Send email (unless dry_run)
    """
    today = date.today()

    if not _is_trading_day(today):
        logger.info(f"{today} is not a trading day. Skipping pipeline.")
        return

    logger.info("=" * 60)
    logger.info(f"PIPELINE START — {today}")
    logger.info("=" * 60)

    # ── Step 1: Market data ───────────────────────────────────────────────
    logger.info("Step 1/7: Collecting market data (CafeF/vnstock)")
    from collector.market_scraper.cafef_scraper import collect_market_data
    market_df = collect_market_data()

    # ── Step 2: ZLP email data ────────────────────────────────────────────
    logger.info("Step 2/7: Reading Outlook emails (DNSE Metabase)")
    from collector.email_ingestion.email_parser import collect_zlp_data
    try:
        zlp_data = collect_zlp_data()
    except Exception as e:
        logger.warning(f"Email ingestion failed: {e}. Continuing with market data only.")
        zlp_data = {}

    # ── Step 3: Normalise + store ─────────────────────────────────────────
    logger.info("Step 3/7: Normalising and storing data")
    from data_processor.normalizer import normalise
    from data_processor.db_manager import DBManager

    unified_df = normalise(market_df, zlp_data)
    db = DBManager()
    db.upsert_rows(unified_df)

    # ── Step 4: Analytics ─────────────────────────────────────────────────
    logger.info("Step 4/7: Running analytics")
    from analytics_engine.calculator import run_analysis
    from analytics_engine.benchmarker import build_benchmark_table

    # Read last 14 trading days for analysis
    analysis_df = db.read_last_n_trading_days(14)
    if analysis_df.empty:
        logger.error("No data in DB after upsert. Check data sources.")
        return

    analysis    = run_analysis(analysis_df)
    bench_table = build_benchmark_table(analysis)

    # ── Step 5: Insights + recommendations ───────────────────────────────
    logger.info("Step 5/7: Generating insights and recommendations")
    from insight_generator.insights import generate_insights, generate_recommendations

    insights        = generate_insights(analysis, bench_table)
    recommendations = generate_recommendations(analysis, bench_table)

    # ── Step 6: Build report ──────────────────────────────────────────────
    logger.info("Step 6/7: Building report")
    from report_writer.report_builder import (
        build_html_report, build_plain_text_summary, save_report
    )

    html_content = build_html_report(
        report_date=today,
        analysis=analysis,
        bench_table=bench_table,
        insights=insights,
        recommendations=recommendations,
    )
    plain_text = build_plain_text_summary(
        report_date=today,
        analysis=analysis,
        bench_table=bench_table,
        insights=insights,
        recommendations=recommendations,
    )
    html_path = save_report(html_content, today)

    # ── Step 7: Send email ────────────────────────────────────────────────
    if dry_run:
        logger.info("Step 7/7: [DRY RUN] Email sending skipped. Report saved to:")
        logger.info(f"  {html_path}")
    else:
        logger.info("Step 7/7: Sending report email")
        from scheduler.mailer import send_report
        send_report(
            html_content=html_content,
            plain_text=plain_text,
            report_date=today,
            html_path=html_path,
        )

    logger.info(f"PIPELINE COMPLETE — {today}")
    logger.info("=" * 60)
    return html_path


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────────────────────

def _scheduled_job():
    """Wrapper called by schedule library — skips non-trading days."""
    tz   = pytz.timezone(config.TIMEZONE)
    now  = datetime.now(tz)
    logger.info(f"Scheduled trigger at {now.strftime('%Y-%m-%d %H:%M %Z')}")
    run_pipeline(dry_run=False)


def start_scheduler():
    """Start the schedule daemon — blocks forever."""
    hour, minute = config.REPORT_TIME.split(":")
    job_time     = f"{int(hour):02d}:{int(minute):02d}"

    logger.info(
        f"Scheduler starting — will run daily at {job_time} {config.TIMEZONE}"
    )
    schedule.every().day.at(job_time).do(_scheduled_job)

    while True:
        schedule.run_pending()
        time.sleep(30)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ZaloPay Stock Intelligence Agent"
    )
    parser.add_argument(
        "--once",  action="store_true",
        help="Run the pipeline once immediately and exit"
    )
    parser.add_argument(
        "--test",  action="store_true",
        help="Dry run: run pipeline but do not send email"
    )
    args = parser.parse_args()

    # Ensure logs directory exists
    (config.BASE_DIR / "logs").mkdir(exist_ok=True)

    if args.once or args.test:
        run_pipeline(dry_run=args.test)
    else:
        start_scheduler()
