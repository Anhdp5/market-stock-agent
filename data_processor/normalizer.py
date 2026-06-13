"""
Data Normalizer
================
Takes raw data from market scraper + email parser and produces a
unified daily DataFrame ready for upsert into SQLite.

Rules:
- Trading days only (Mon–Fri, excluding VN public holidays)
- Dates matched exactly — never compare mismatched dates
- Missing values filled with NaN (not zero)
- ZLPActiveUsers is monthly; forward-filled to daily for trend display
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging
from datetime import date, timedelta
from typing import Dict, Optional

import pandas as pd

import config

logger = logging.getLogger(__name__)

METRIC_COLUMNS = [
    "MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume",
    "ZLPNewAccount", "ZLPTradingTransaction", "ZLPTradingVolume",
    "ZLPActiveUsers", "ZLPTransactionbyusersegment",
]


def _is_trading_day(d: date) -> bool:
    """Returns True if `d` is a Vietnamese stock exchange trading day."""
    if d.weekday() >= 5:        # Saturday=5, Sunday=6
        return False
    if d.strftime("%Y-%m-%d") in config.VN_HOLIDAYS_2024_2026:
        return False
    return True


def build_trading_day_spine(start: date, end: date) -> pd.DataFrame:
    """Return a DataFrame with one row per trading day between start and end."""
    days = []
    current = start
    while current <= end:
        if _is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return pd.DataFrame({"date": days})


def normalise(
    market_df: Optional[pd.DataFrame],
    zlp_data:  Dict[str, pd.DataFrame],
    lookback_days: int = config.LOOKBACK_DAYS,
) -> pd.DataFrame:
    """
    Merge market + ZLP data onto a trading-day spine.

    Parameters
    ----------
    market_df   : DataFrame from market scraper (date, MarketTransaction, MarketVolume, BuyVolume, SellVolume)
    zlp_data    : Dict of metric_key → DataFrame (date, <metric_key>)
    lookback_days: How many calendar days back to build the spine

    Returns
    -------
    Unified daily DataFrame with all columns.
    """
    end_dt   = date.today()
    start_dt = end_dt - timedelta(days=lookback_days)

    # ── Build spine ────────────────────────────────────────────────────────
    spine = build_trading_day_spine(start_dt, end_dt)
    logger.info(f"Trading day spine: {len(spine)} days ({start_dt} → {end_dt})")

    unified = spine.copy()

    # ── Merge market data ──────────────────────────────────────────────────
    if market_df is not None and not market_df.empty:
        market_df = market_df.copy()
        market_df["date"] = pd.to_datetime(market_df["date"]).dt.date
        # Keep only trading days
        market_df = market_df[market_df["date"].apply(_is_trading_day)]
        unified = unified.merge(market_df, on="date", how="left")
        logger.info(f"Merged market data: {market_df['date'].nunique()} unique dates")
    else:
        for col in ["MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume"]:
            unified[col] = None

    # ── Merge ZLP metrics ──────────────────────────────────────────────────
    for metric_key, metric_df in zlp_data.items():
        if metric_df is None or metric_df.empty:
            unified[metric_key] = None
            continue

        metric_df = metric_df.copy()
        metric_df["date"] = pd.to_datetime(metric_df["date"]).dt.date
        metric_df = metric_df[metric_df["date"].apply(_is_trading_day)]
        metric_df = metric_df[["date", metric_key]].drop_duplicates("date")

        unified = unified.merge(metric_df, on="date", how="left")
        logger.info(
            f"Merged {metric_key}: {metric_df['date'].nunique()} unique dates"
        )

    # ── Ensure all columns present ─────────────────────────────────────────
    for col in METRIC_COLUMNS:
        if col not in unified.columns:
            unified[col] = None

    # ── Forward-fill ZLPActiveUsers (monthly metric → carry to daily) ──────
    if "ZLPActiveUsers" in unified.columns:
        unified["ZLPActiveUsers"] = (
            unified["ZLPActiveUsers"]
            .ffill()       # carry last known monthly value forward
        )

    unified = unified.sort_values("date").reset_index(drop=True)

    n_populated = unified[METRIC_COLUMNS].notna().any(axis=1).sum()
    logger.info(f"Normalised unified table: {len(unified)} rows, {n_populated} have data")
    return unified


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    spine = build_trading_day_spine(date(2026, 5, 1), date(2026, 6, 13))
    print(f"Trading days May-Jun 2026: {len(spine)}")
    print(spine.tail(10).to_string())
