"""
ZaloPay Stock Intelligence Agent - Main Entry Point

Usage:
  python main.py                                        # Daily scheduler daemon
  python main.py --once                                 # Run today, send email
  python main.py --test                                 # Run today, no email
  python main.py --test --date 2026-06-10               # Specific date
  python main.py --test --from 2026-06-01               # From date to today
  python main.py --test --from 2026-06-01 --to 2026-06-13  # Date range
  python main.py --once --from 2026-06-01 --to 2026-06-13  # Range + send email
  python main.py --test --date 2026-06-07 --force       # Force on non-trading day
"""

import argparse
import logging
import sys
from datetime import date, datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Invalid date '{}'. Use YYYY-MM-DD format.".format(s)
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ZaloPay Stock Intelligence Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true",
                      help="Run pipeline and send email")
    mode.add_argument("--test", action="store_true",
                      help="Dry run - generate report but skip email")

    parser.add_argument("--date", type=_parse_date, metavar="YYYY-MM-DD",
                        help="Run for a specific date")
    parser.add_argument("--from", dest="date_from", type=_parse_date,
                        metavar="YYYY-MM-DD",
                        help="Start of date range")
    parser.add_argument("--to", dest="date_to", type=_parse_date,
                        metavar="YYYY-MM-DD",
                        help="End of date range (defaults to today)")
    parser.add_argument("--force", action="store_true",
                        help="Run even on weekends/holidays")

    args = parser.parse_args()

    if args.date and (args.date_from or args.date_to):
        parser.error("--date cannot be combined with --from / --to")

    dry_run = not args.once

    from scheduler.main_scheduler import (
        run_pipeline, run_pipeline_range, start_scheduler
    )

    if args.date_from or args.date_to:
        start = args.date_from or date.today()
        end   = args.date_to   or date.today()
        if start > end:
            parser.error("--from {} is after --to {}".format(start, end))
        paths = run_pipeline_range(
            start_date=start,
            end_date=end,
            dry_run=dry_run,
            force=args.force,
        )
        print("\n{} report(s) saved:".format(len(paths)))
        for p in paths:
            print("  {}".format(p))

    elif args.once or args.test or args.date:
        run_date = args.date or date.today()
        path = run_pipeline(
            dry_run=dry_run,
            run_date=run_date,
            force=args.force,
        )
        if path:
            print("\nReport saved to: {}".format(path))

    else:
        start_scheduler()
