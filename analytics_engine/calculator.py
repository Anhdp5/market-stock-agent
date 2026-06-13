"""
Analytics Calculator
=====================
For each metric computes:
  - Latest value (D0)
  - Previous day value (D-1)
  - D1 vs D0 change %
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

ANALYSIS_WINDOW = config.ANALYSIS_WINDOW   # 7 trading days

METRIC_LABELS = {
    "MarketTransaction":           "Market Matched Orders",
    "MarketVolume":                "Market Trading Volume",
    "BuyVolume":                   "Market Buy Volume",
    "SellVolume":                  "Market Sell Volume",
    "ZLPNewAccount":               "ZLP New Accounts",
    "ZLPTradingTransaction":       "ZLP Matched Orders",
    "ZLPTradingVolume":            "ZLP Trading Value",
    "ZLPActiveUsers":              "ZLP Active Users",
    "ZLPTransactionbyusersegment": "ZLP Orders by Segment",
}

MARKET_METRICS = ["MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume"]
ZLP_METRICS    = [
    "ZLPNewAccount", "ZLPTradingTransaction", "ZLPTradingVolume",
    "ZLPActiveUsers", "ZLPTransactionbyusersegment",
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
    """
    Given a time-ordered Series of daily values (NaN for missing),
    return a stats dict.
    """
    clean = series.dropna()
    if clean.empty:
        return {
            "d0": None, "d1": None, "d0_vs_d1_pct": None,
            "avg_7d": None, "d0_vs_avg_pct": None,
            "wow_pct": None, "trend": "insufficient_data",
            "available_days": 0,
        }

    d0  = clean.iloc[-1]   if len(clean) >= 1 else None
    d1  = clean.iloc[-2]   if len(clean) >= 2 else None
    d7  = clean.tail(ANALYSIS_WINDOW)
    avg = d7.mean()        if len(d7) >= 1 else None

    # WoW: compare this week's average vs previous week's average
    prev_week = clean.iloc[-(ANALYSIS_WINDOW * 2):-(ANALYSIS_WINDOW)] if len(clean) >= ANALYSIS_WINDOW * 2 else pd.Series(dtype=float)
    wow_pct   = _pct_change(avg, prev_week.mean()) if not prev_week.empty and avg is not None else None

    return {
        "d0":           round(d0,  2) if d0  is not None else None,
        "d1":           round(d1,  2) if d1  is not None else None,
        "d0_vs_d1_pct": _pct_change(d0, d1),
        "avg_7d":       round(avg, 2) if avg is not None else None,
        "d0_vs_avg_pct":_pct_change(d0, avg),
        "wow_pct":      wow_pct,
        "trend":        _trend(series.tail(ANALYSIS_WINDOW)),
        "available_days": len(clean),
    }


def run_analysis(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """
    Run all metric calculations on a unified daily DataFrame.

    Returns
    -------
    analysis : dict keyed by metric name, value is stats dict plus label.
    """
    if df is None or df.empty:
        logger.error("Empty DataFrame passed to analytics engine")
        return {}

    df = df.sort_values("date").reset_index(drop=True)

    # Take the last 2 × ANALYSIS_WINDOW trading days for calculations
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
    # Quick smoke test with synthetic data
    import numpy as np
    dates = pd.bdate_range("2026-05-01", periods=20)
    synthetic = pd.DataFrame({
        "date":                  [d.date() for d in dates],
        "MarketVolume":          np.random.randint(8000, 15000, 20).astype(float),
        "MarketTransaction":     np.random.randint(300000, 600000, 20).astype(float),
        "BuyVolume":             np.random.randint(4000, 8000, 20).astype(float),
        "SellVolume":            np.random.randint(4000, 8000, 20).astype(float),
        "ZLPTradingTransaction": np.random.randint(500, 2000, 20).astype(float),
        "ZLPTradingVolume":      np.random.randint(5e9, 2e10, 20).astype(float),
        "ZLPNewAccount":         np.random.randint(100, 500, 20).astype(float),
        "ZLPActiveUsers":        np.random.randint(5000, 8000, 20).astype(float),
        "ZLPTransactionbyusersegment": np.random.randint(500, 2000, 20).astype(float),
    })
    result = run_analysis(synthetic)
    for k, v in result.items():
        print(f"{k}: d0={v['d0']}, wow={v['wow_pct']}%, trend={v['trend']}")
