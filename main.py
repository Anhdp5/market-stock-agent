"""
ZaloPay Stock Intelligence Agent — Main Entry Point
=====================================================

Usage examples:
  python main.py                                   # Start daily scheduler (08:00 AM daemon)
  python main.py --once                            # Run for today, send email
  python main.py --test                            # Run for today, no email (dry run)

  python main.py --test --date 2026-06-10          # Run for a specific date
  python main.py --test --from 2026-06-01          # Run from a date up to today
  python main.py --test --from 2026-06-01 --to 2026-06-13   # Run for a date range
  python main.py --once --from 2026-06-01 --to 2026-06-13   # Range + send email per day

  python main.py --test --date 2026-06-07 --force  # Force run on a non-trading day (weekend)
"""

import argparse
import logging
import sys
from datetime import date, datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
