"""
Market vs ZaloPay Benchmarker
==============================
Compares ZaloPay growth rates against the overall market and
assigns an assessment: Outperform / In Line / Underperform.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


# Gap thresholds for assessment labels
OUTPERFORM_GAP_PP =  2.0   # ZLP better than market by ≥ 2 percentage points
UNDERPERFORM_GAP_PP = -2.0  # ZLP worse  than market by ≥ 2 percentage points


COMPARABLE_PAIRS = [
    # (market_metric, zlp_metric, comparison_label)
    ("MarketTransaction",  "ZLPTradingTransaction", "Trading Transactions"),
    ("MarketVolume",       "ZLPTradingVolume",       "Trading Volume / Value"),
    ("BuyVolume",          None,                     None),   # no direct ZLP equivalent
]


def _assessment(gap_pp: Optional[float]) -> str:
    if gap_pp is None:
        return "N/A"
    if gap_pp >= OUTPERFORM_GAP_PP:
        return "Outperform"
    if gap_pp <= UNDERPERFORM_GAP_PP:
        return "Underperform"
    return "In Line"


def build_benchmark_table(
    analysis: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Build a benchmark comparison table row by row.

    Returns a list of dicts:
    {
        metric_label, market_growth_pct, zlp_growth_pct,
        gap_pp, assessment, narrative
    }
    """
    rows = []

    for mkt_key, zlp_key, label in COMPARABLE_PAIRS:
        if label is None:
            continue

        mkt_stats = analysis.get(mkt_key, {})
        zlp_stats = analysis.get(zlp_key, {}) if zlp_key else {}

        mkt_wow  = mkt_stats.get("wow_pct")
        zlp_wow  = zlp_stats.get("wow_pct") if zlp_stats else None
        mkt_d1   = mkt_stats.get("d0_vs_d1_pct")
        zlp_d1   = zlp_stats.get("d0_vs_d1_pct") if zlp_stats else None

        # Use WoW as primary growth metric
        gap_pp = None
        if mkt_wow is not None and zlp_wow is not None:
            gap_pp = round(zlp_wow - mkt_wow, 2)

        asmt = _assessment(gap_pp)

        # Generate narrative sentence
        narrative = _build_narrative(
            label, mkt_wow, zlp_wow, mkt_d1, zlp_d1, gap_pp, asmt
        )

        rows.append({
            "metric_label":      label,
            "mkt_key":           mkt_key,
            "zlp_key":           zlp_key,
            "market_growth_pct": mkt_wow,
            "zlp_growth_pct":    zlp_wow,
            "gap_pp":            gap_pp,
            "assessment":        asmt,
            "mkt_d1":            mkt_d1,
            "zlp_d1":            zlp_d1,
            "narrative":         narrative,
        })

    # ZLPNewAccount — no market equivalent: compare against own 7d average
    na_stats = analysis.get("ZLPNewAccount", {})
    if na_stats:
        d0_vs_avg = na_stats.get("d0_vs_avg_pct")
        wow       = na_stats.get("wow_pct")
        trend     = na_stats.get("trend", "insufficient_data")

        if wow is not None:
            if wow > 5:
                asmt = "Improving"
            elif wow < -5:
                asmt = "Declining"
            else:
                asmt = "Stable"
        else:
            asmt = "N/A"

        rows.append({
            "metric_label":      "New Accounts",
            "mkt_key":           None,
            "zlp_key":           "ZLPNewAccount",
            "market_growth_pct": None,
            "zlp_growth_pct":    wow,
            "gap_pp":            None,
            "assessment":        asmt,
            "mkt_d1":            None,
            "zlp_d1":            na_stats.get("d0_vs_d1_pct"),
            "narrative":         _build_new_account_narrative(
                wow, d0_vs_avg, trend
            ),
        })

    return rows


def _build_narrative(
    label: str,
    mkt_wow: Optional[float],
    zlp_wow: Optional[float],
    mkt_d1:  Optional[float],
    zlp_d1:  Optional[float],
    gap_pp:  Optional[float],
    asmt:    str,
) -> str:
    parts = []

    if mkt_wow is not None and zlp_wow is not None:
        mkt_dir = "grew" if mkt_wow >= 0 else "declined"
        zlp_dir = "grew" if zlp_wow >= 0 else "declined"

        parts.append(
            f"Over the last 7 trading days, market {label.lower()} {mkt_dir} "
            f"{abs(mkt_wow):.1f}% WoW while ZaloPay {zlp_dir} {abs(zlp_wow):.1f}% WoW."
        )

        if asmt == "Outperform":
            parts.append(
                f"ZaloPay is outperforming the market by {abs(gap_pp):.1f} pp, "
                f"indicating stronger platform engagement relative to market conditions."
            )
        elif asmt == "Underperform":
            parts.append(
                f"ZaloPay is underperforming the market by {abs(gap_pp):.1f} pp, "
                f"suggesting potential platform-specific headwinds or acquisition gaps."
            )
        else:
            parts.append(
                f"ZaloPay is broadly tracking the market ({gap_pp:+.1f} pp gap), "
                f"suggesting performance is primarily macro-driven."
            )

    elif mkt_d1 is not None and zlp_d1 is not None:
        parts.append(
            f"Yesterday: market {label.lower()} changed {mkt_d1:+.1f}% "
            f"vs ZaloPay {zlp_d1:+.1f}%."
        )
    else:
        parts.append(f"Insufficient data to benchmark {label} Market vs ZaloPay.")

    return " ".join(parts)


def _build_new_account_narrative(
    wow: Optional[float],
    d0_vs_avg: Optional[float],
    trend: str,
) -> str:
    if wow is None:
        return "New account data unavailable for benchmarking."

    dir_str = "increased" if wow >= 0 else "decreased"
    out = f"New account openings {dir_str} {abs(wow):.1f}% WoW. "

    if d0_vs_avg is not None:
        if d0_vs_avg > 10:
            out += "Current daily volume is running above the 7-day average, signalling improving momentum. "
        elif d0_vs_avg < -10:
            out += "Current daily volume is below the 7-day average, suggesting softening demand. "

    trend_map = {"up": "accelerating", "down": "decelerating", "flat": "stable"}
    out += f"Trend is {trend_map.get(trend, 'unclear')} over the analysis window."

    return out
