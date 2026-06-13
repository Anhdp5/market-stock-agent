"""
Data Normalizer
================
Merges market + ZLP data onto a trading-day spine.
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


def _is_trading_day(d):
    if d.weekday() >= 5:
        return False
    if d.strftime("%Y-%m-%d") in config.VN_HOLIDAYS_2024_2026:
        return False
    return True


def build_trading_day_spine(start, end):
    days = []
    current = start
    while current <= end:
        if _is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return pd.DataFrame({"date": days})


def normalise(market_df, zlp_data, lookback_days=None, end_date=None):
    """
    Merge market + ZLP data onto a trading-day spine.

    Parameters
    ----------
    market_df     : DataFrame from market scraper
    zlp_data      : Dict of metric_key -> DataFrame
    lookback_days : Calendar days back from end_date to build spine
    end_date      : Last date of spine (defaults to today)
    """
    if lookback_days is None:
        lookback_days = config.LOOKBACK_DAYS

    end_dt   = end_date or date.today()
    start_dt = end_dt - timedelta(days=lookback_days)

    spine   = build_trading_day_spine(start_dt, end_dt)
    unified = spine.copy()
    logger.info("Trading day spine: {} days ({} -> {})".format(len(spine), start_dt, end_dt))

    # Merge market data
    if market_df is not None and not market_df.empty:
        market_df = market_df.copy()
        market_df["date"] = pd.to_datetime(market_df["date"]).dt.date
        market_df = market_df[market_df["date"].apply(_is_trading_day)]
        unified = unified.merge(market_df, on="date", how="left")
        logger.info("Merged market data: {} unique dates".format(market_df["date"].nunique()))
    else:
        for col in ["MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume"]:
            unified[col] = None

    # Merge ZLP metrics
    for metric_key, metric_df in zlp_data.items():
        if metric_df is None or metric_df.empty:
            unified[metric_key] = None
            continue
        metric_df = metric_df.copy()
        metric_df["date"] = pd.to_datetime(metric_df["date"]).dt.date
        metric_df = metric_df[metric_df["date"].apply(_is_trading_day)]
        metric_df = metric_df[["date", metric_key]].drop_duplicates("date")
        unified = unified.merge(metric_df, on="date", how="left")
        logger.info("Merged {}: {} unique dates".format(metric_key, metric_df["date"].nunique()))

    # Ensure all columns present
    for col in METRIC_COLUMNS:
        if col not in unified.columns:
            unified[col] = None

    # Forward-fill ZLPActiveUsers (monthly -> daily)
    if "ZLPActiveUsers" in unified.columns:
        unified["ZLPActiveUsers"] = unified["ZLPActiveUsers"].ffill()

    unified = unified.sort_values("date").reset_index(drop=True)
    logger.info("Normalised: {} rows".format(len(unified)))
    return unified


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    spine = build_trading_day_spine(date(2026, 5, 1), date(2026, 6, 13))
    print("Trading days May-Jun 2026:", len(spine))
    print(spine.tail(10).to_string())
