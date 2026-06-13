"""
ZaloPay Stock Intelligence Agent — Main Entry Point
=====================================================
Convenience wrapper around scheduler/main_scheduler.py.

Usage:
  python main.py             # Start daily scheduler (08:00 AM daemon)
  python main.py --once      # Run pipeline once now (sends email)
  python main.py --test      # Run pipeline once, skip email
"""

from scheduler.main_scheduler import run_pipeline, start_scheduler
import argparse
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZaloPay Stock Intelligence Agent")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--test", action="store_true", help="Dry run (no email)")
    args = parser.parse_args()

    if args.once or args.test:
        path = run_pipeline(dry_run=args.test)
        if path:
            print(f"\nReport saved to: {path}")
        sys.exit(0)
    else:
        start_scheduler()
