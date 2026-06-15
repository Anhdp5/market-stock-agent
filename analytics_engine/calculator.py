"""
Analytics Calculator
=====================
For each metric computes:
  - Latest value (D0)
  - Previous day value (D-1)
  - D0 vs D1 change %
  - 7-day average
  - Current vs 7-day average %
  - WoW (week-over-week) growth %
  - Trend direction: up / down / flat / insufficient_data
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging
from typing import Dict, Any, Optional

import pandas as pd
import numpy as np

import config

logger = logging.getLogger(__name__)

ANALYSIS_WINDOW   = config.ANALYSIS_WINDOW     # 7 trading days (rolling average)
WEEK_TRADING_DAYS = config.WEEK_TRADING_DAYS   # 5 trading days = one trading week

METRIC_LABELS = {
    "MarketVolume":       "Market Trading Volume",
    "MarketValue":        "Market Trading Value (B VND)",
    "BuyVolume":          "Market Buy Volume",
    "SellVolume":         "Market Sell Volume",
    "MarketOrderCount":   "Market Orders",
    "MarketBuyOrders":    "Market Buy Orders",
    "MarketSellOrders":   "Market Sell Orders",
    "ZLPNewAccount":      "ZLP New Accounts",
    "ZLPTransaction":     "ZLP Orders",
    "ZLPValue":           "ZLP Trading Value (B VND)",
    "ZLPActiveUsers":     "ZLP Active Users",
    "ZLPActiveSellUsers": "ZLP Active Sell Users",
    "ZLPActiveBuyUsers":  "ZLP Active Buy Users",
    "ZLPActiveUsersMonthly": "ZLP Monthly Active Users",
}

MARKET_METRICS = [
    "MarketVolume", "MarketValue", "BuyVolume", "SellVolume",
    "MarketOrderCount", "MarketBuyOrders", "MarketSellOrders",
]
ZLP_METRICS = [
    "ZLPNewAccount", "ZLPTransaction", "ZLPValue",
    "ZLPActiveUsers", "ZLPActiveSellUsers", "ZLPActiveBuyUsers",
    "ZLPActiveUsersMonthly",
]


def _pct_change(new_val: float, old_val: float) -> Optional[float]:
    if old_val is None or old_val == 0 or pd.isna(old_val):
        return None
    if new_val is None or pd.isna(new_val):
        return None
    return round((new_val - old_val) / abs(old_val) * 100, 2)


def _trend(series: pd.Series) -> str:
    """Determine trend from last N non-null values using linear regression slope."""
    vals = series.dropna().values
    if len(vals) < 3:
        return "insufficient_data"
    x   = np.arange(len(vals))
    fit = np.polyfit(x, vals, 1)
    slope_pct = fit[0] / (abs(vals.mean()) + 1e-9) * 100
    if slope_pct > 1.0:
        return "up"
    if slope_pct < -1.0:
        return "down"
    return "flat"


def compute_metric_stats(series: pd.Series) -> Dict[str, Any]:
    clean = series.dropna()
    if clean.empty:
        return {
            "d0": None, "d1": None, "d0_vs_d1_pct": None,
            "avg_7d": None, "d0_vs_avg_pct": None,
            "wow_pct": None, "trend": "insufficient_data",
            "available_days": 0,
        }

    d0  = clean.iloc[-1] if len(clean) >= 1 else None
    d1  = clean.iloc[-2] if len(clean) >= 2 else None
    d7  = clean.tail(ANALYSIS_WINDOW)
    avg = d7.mean()      if len(d7) >= 1 else None

    # ── Week-over-week ────────────────────────────────────────────────────
    # A trading week is 5 days (markets are closed on weekends), so two weeks
    # is 10 trading days — NOT 14. WoW compares the average of the last 5
    # trading days against the 5 trading days before that.
    #   (The old code required ANALYSIS_WINDOW*2 = 14 points, which a full
    #    two trading weeks never reaches, leaving WoW permanently empty.)
    week = WEEK_TRADING_DAYS
    n    = len(clean)
    if n >= 2 * week:
        recent_block = clean.iloc[-week:]
        prior_block  = clean.iloc[-2 * week:-week]
        wow_pct = _pct_change(recent_block.mean(), prior_block.mean())
    elif n >= 4:
        # Less than two full trading weeks loaded: fall back to a symmetric
        # half-split (min 2 days per block) so sparse metrics still yield a WoW.
        block = n // 2
        wow_pct = _pct_change(clean.iloc[-block:].mean(),
                              clean.iloc[-2 * block:-block].mean())
    else:
        wow_pct = None

    return {
        "d0":            round(d0,  2) if d0  is not None else None,
        "d1":            round(d1,  2) if d1  is not None else None,
        "d0_vs_d1_pct":  _pct_change(d0, d1),
        "avg_7d":        round(avg, 2) if avg is not None else None,
        "d0_vs_avg_pct": _pct_change(d0, avg),
        "wow_pct":       wow_pct,
        "trend":         _trend(series.tail(ANALYSIS_WINDOW)),
        "available_days": len(clean),
    }


def run_analysis(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    if df is None or df.empty:
        logger.error("Empty DataFrame passed to analytics engine")
        return {}

    df = df.sort_values("date").reset_index(drop=True)
    window_df = df.tail(ANALYSIS_WINDOW * 2)

    analysis: Dict[str, Dict[str, Any]] = {}

    for metric in list(METRIC_LABELS.keys()):
        if metric not in window_df.columns:
            continue
        series = window_df[metric].reset_index(drop=True)
        stats  = compute_metric_stats(series)
        stats["label"] = METRIC_LABELS[metric]
        analysis[metric] = stats
        logger.debug(
            f"{metric}: d0={stats['d0']}, "
            f"d0_vs_d1={stats['d0_vs_d1_pct']}%, "
            f"wow={stats['wow_pct']}%"
        )

    return analysis


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    import numpy as np
    dates = pd.bdate_range("2026-05-01", periods=20)
    synthetic = pd.DataFrame({
        "date":             [d.date() for d in dates],
        "MarketVolume":     np.random.randint(8000, 15000, 20).astype(float),
        "MarketValue":      np.random.uniform(10, 20, 20),
        "BuyVolume":        np.random.randint(4000, 8000, 20).astype(float),
        "SellVolume":       np.random.randint(4000, 8000, 20).astype(float),
        "ZLPTransaction":   np.random.randint(500, 2000, 20).astype(float),
        "ZLPNewAccount":    np.random.randint(100, 500, 20).astype(float),
        "ZLPActiveUsers":   np.random.randint(5000, 8000, 20).astype(float),
        "ZLPActiveSellUsers": np.random.randint(1000, 3000, 20).astype(float),
        "ZLPActiveBuyUsers":  np.random.randint(1000, 3000, 20).astype(float),
    })
    result = run_analysis(synthetic)
    for k, v in result.items():
        print(f"{k}: d0={v['d0']}, wow={v['wow_pct']}%, trend={v['trend']}")
