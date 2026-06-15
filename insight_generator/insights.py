"""
Insight Generator
==================
Applies consulting-style logic to produce:
1. Ranked insights (What happened → Why → Business implication)
2. Actionable recommendations grouped by team (Product / Marketing / CRM)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import json
import logging
from typing import Dict, Any, List, Optional, Tuple

from insight_generator import llm_client

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Rule-based insight generation (fallback when the LLM is unavailable)
# ─────────────────────────────────────────────────────────────────────────────

def _rule_based_insights(
    analysis:    Dict[str, Dict[str, Any]],
    bench_table: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """
    Returns a list of insight dicts:
    { priority, what, why, implication }
    Sorted by priority (1 = highest).
    """
    insights: List[Tuple[int, Dict[str, str]]] = []

    def add(priority: int, what: str, why: str, implication: str):
        insights.append((priority, {"what": what, "why": why, "implication": implication}))

    # ── Benchmark-level insights ───────────────────────────────────────────

    for row in bench_table:
        asmt    = row.get("assessment", "N/A")
        mkt_wow = row.get("market_growth_pct")
        zlp_wow = row.get("zlp_growth_pct")
        gap     = row.get("gap_pp")
        label   = row.get("metric_label", "")

        if asmt == "Outperform" and gap is not None:
            if mkt_wow is not None and mkt_wow < -5:
                # ZLP holding up in a down market
                add(1,
                    f"Market {label.lower()} fell {abs(mkt_wow):.1f}% WoW, "
                    f"but ZaloPay declined only {abs(zlp_wow):.1f}%.",
                    "ZaloPay's user base shows stronger retention and trading intent "
                    "than the broader market. High-commitment users continue to trade "
                    "despite weaker sentiment.",
                    "Platform stickiness is a competitive moat. Prioritise retention "
                    "campaigns to lock in this cohort before sentiment recovers."
                )
            else:
                add(2,
                    f"ZaloPay {label.lower()} grew {abs(zlp_wow):.1f}% WoW vs market {abs(mkt_wow):.1f}%.",
                    f"ZaloPay is gaining market share — outperforming by {abs(gap):.1f} pp. "
                    "This likely reflects successful acquisition or product improvements.",
                    "Accelerate investment in channels and features driving the outperformance."
                )

        elif asmt == "Underperform" and gap is not None:
            if mkt_wow is not None and mkt_wow > 5:
                # Market up but ZLP lagging
                add(1,
                    f"Market {label.lower()} rose {abs(mkt_wow):.1f}% WoW but "
                    f"ZaloPay grew only {abs(zlp_wow):.1f}% — a {abs(gap):.1f} pp gap.",
                    "ZaloPay is losing relative share during a market rally. "
                    "Users may be migrating to competitors with better order execution or UX.",
                    "Conduct competitive UX audit. Investigate order execution speeds, "
                    "margin rates, and competitor promotions to close the gap."
                )
            else:
                add(2,
                    f"ZaloPay {label.lower()} underperformed market by {abs(gap):.1f} pp WoW.",
                    "Platform-specific friction may be deterring users who are still "
                    "active in the market. Possible causes: app errors, slow matching, "
                    "or aggressive competitor promotions.",
                    "Run a funnel audit — identify where ZaloPay users drop off vs. "
                    "market expectations and address the highest-friction step first."
                )

    # ── ZLP-specific metric insights ───────────────────────────────────────

    # New Accounts
    na = analysis.get("ZLPNewAccount", {})
    if na:
        wow   = na.get("wow_pct")
        trend = na.get("trend", "")
        d0_vs_avg = na.get("d0_vs_avg_pct")

        if wow is not None and wow < -15:
            add(1,
                f"New account openings declined {abs(wow):.1f}% WoW.",
                "Acquisition funnel may have degraded — possibly due to reduced "
                "marketing spend, a broken onboarding step, or market disinterest.",
                "Run acquisition funnel diagnostics immediately. Check drop-off at "
                "each KYC step and compare marketing spend levels."
            )
        elif wow is not None and wow > 20:
            add(3,
                f"New account openings surged {abs(wow):.1f}% WoW.",
                "A recent campaign, market rally, or viral moment likely drove the spike.",
                "Capture these new users with an onboarding push — first-trade incentives "
                "and guided tutorials dramatically improve D7 activation rates."
            )

    # Active Users
    au = analysis.get("ZLPActiveUsers", {})
    if au:
        wow = au.get("wow_pct")
        if wow is not None and wow < -10:
            add(2,
                f"Active user count dropped {abs(wow):.1f}% vs prior period.",
                "Users are opening accounts but not returning. Likely driven by weak "
                "market sentiment or low perceived value of the platform.",
                "Deploy re-engagement push notifications with personalised portfolio "
                "performance summaries and market-opportunity alerts."
            )

    # Trading volume vs transactions divergence
    tx_stats = analysis.get("ZLPTransaction", {})
    vol_stats = analysis.get("ZLPVolume", {})
    if tx_stats and vol_stats:
        tx_wow  = tx_stats.get("wow_pct")
        vol_wow = vol_stats.get("wow_pct")
        if tx_wow is not None and vol_wow is not None:
            divergence = vol_wow - tx_wow
            if divergence > 15:
                add(3,
                    f"ZaloPay trading value grew {abs(vol_wow):.1f}% WoW but "
                    f"order count grew only {abs(tx_wow):.1f}% — value/order ratio rising.",
                    "Whale users (high-value traders) are increasing position sizes. "
                    "The platform is concentrating revenue among a smaller, high-value cohort.",
                    "Launch a VIP/premium tier for high-value traders with dedicated "
                    "support and margin financing to deepen this relationship."
                )
            elif divergence < -15:
                add(3,
                    f"ZaloPay order count grew {abs(tx_wow):.1f}% WoW but "
                    f"trading value grew only {abs(vol_wow):.1f}%.",
                    "More users are trading, but with smaller order sizes. "
                    "Retail/new investor activity is rising, but monetisation per user is falling.",
                    "Introduce trading education content and portfolio goal-setting features "
                    "to gradually increase average order size among the retail cohort."
                )

    # Segment analysis
    seg = analysis.get("ZLPTransactionBySegment", {})
    if seg:
        wow = seg.get("wow_pct")
        if wow is not None and wow < -10:
            add(3,
                f"Orders across all user segments declined {abs(wow):.1f}% WoW.",
                "Broad-based decline indicates macro headwinds rather than "
                "segment-specific issues.",
                "Focus retention on the top 20% of users by trading value — "
                "these users have the highest return-probability in a recovery."
            )

    # Sort by priority and return
    insights.sort(key=lambda x: x[0])
    return [item for _, item in insights[:5]]   # top 5 insights


# ─────────────────────────────────────────────────────────────────────────────
# Rule-based recommendation engine (fallback when the LLM is unavailable)
# ─────────────────────────────────────────────────────────────────────────────

def _rule_based_recommendations(
    analysis:    Dict[str, Dict[str, Any]],
    bench_table: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """
    Returns recommendations grouped by team.
    { "Product": [...], "Marketing": [...], "CRM": [...] }
    """
    product   : List[Tuple[int, str]] = []
    marketing : List[Tuple[int, str]] = []
    crm       : List[Tuple[int, str]] = []

    def _p(priority: int, msg: str): product.append((priority, msg))
    def _m(priority: int, msg: str): marketing.append((priority, msg))
    def _c(priority: int, msg: str): crm.append((priority, msg))

    # Assess overall market vs ZLP performance
    tx_bench  = next((r for r in bench_table if r["mkt_key"] == "MarketTransaction"), {})
    vol_bench = next((r for r in bench_table if r["mkt_key"] == "MarketVolume"), {})
    na_bench  = next((r for r in bench_table if r.get("zlp_key") == "ZLPNewAccount"), {})

    tx_asmt  = tx_bench.get("assessment", "N/A")
    vol_asmt = vol_bench.get("assessment", "N/A")
    na_asmt  = na_bench.get("assessment", "N/A")

    # ── Product ────────────────────────────────────────────────────────────
    _p(1, "Enable real-time watchlist price alerts to drive intraday trading triggers.")
    _p(2, "Improve portfolio P&L dashboard with sector-level attribution to increase session depth.")

    if vol_asmt == "Underperform":
        _p(1, "Audit order execution speed — reduce latency to below 500ms to recover high-value traders.")
        _p(2, "A/B test one-tap reorder feature for repeat trades to increase order frequency.")

    if tx_asmt == "Outperform":
        _p(3, "Introduce margin trading or leverage features to monetise high-frequency traders.")

    mkt_vol = analysis.get("MarketVolume", {})
    if mkt_vol.get("trend") == "down":
        _p(2, "Launch 'Market Opportunity Finder' feature highlighting undervalued stocks to stimulate trading intent during low-sentiment periods.")

    # ── Marketing ─────────────────────────────────────────────────────────
    _m(1, "Focus paid acquisition on intent-based keywords (e.g. 'mở tài khoản chứng khoán') — convert market interest into ZaloPay accounts.")

    if na_asmt == "Declining":
        _m(1, "Activate referral bonus campaign — offer existing users incentive for each successful new account activation.")
    elif na_asmt == "Improving":
        _m(2, "Scale top-performing acquisition channels by 20% while momentum is positive.")

    mkt_wow = vol_bench.get("market_growth_pct")
    if mkt_wow is not None and mkt_wow < -10:
        _m(2, "Run 'Buy the Dip' educational content campaign — reframe market decline as an opportunity to attract new investors.")
    elif mkt_wow is not None and mkt_wow > 10:
        _m(1, "Launch FOMO-driven urgency campaign ('Market up X% this week') to convert fence-sitters into first-time traders.")

    # ── CRM / Retention ────────────────────────────────────────────────────
    _c(1, "Re-engage dormant users (no trade in 14+ days) with personalised portfolio performance summaries and market recap push notifications.")
    _c(2, "Identify users who opened accounts but never traded — trigger a first-trade incentive (fee waiver or bonus) within 72 hours of signup.")

    au = analysis.get("ZLPActiveUsers", {})
    if au.get("trend") == "down":
        _c(1, "Segment churning users by last trading value. Deploy targeted win-back offers to top 30% of value at-risk users.")

    seg = analysis.get("ZLPTransactionBySegment", {})
    if seg.get("wow_pct") is not None and seg["wow_pct"] < -5:
        _c(2, "Send whale users (top 10% by GTGD) premium market intelligence briefings to reinforce platform value and prevent migration.")

    _c(3, "Automate weekly portfolio performance email to all active users — users who receive performance summaries show 2–3× higher retention.")

    # Sort by priority, take top 3–5 per team
    def top(lst, n=3):
        return [msg for _, msg in sorted(lst)[:n]]

    return {
        "Product":   top(product,  4),
        "Marketing": top(marketing, 3),
        "CRM":       top(crm,      4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# LLM-driven generation (primary) — Qwen via GreenNode AI Platform
# ─────────────────────────────────────────────────────────────────────────────

_ANALYST_SYSTEM = (
    "You are a senior business & equity analyst for ZaloPay's stock-trading "
    "platform in Vietnam. You compare ZaloPay (ZLP) trading metrics against the "
    "broader HOSE market and turn the numbers into sharp, decision-ready output "
    "for Product, Marketing and CRM teams. You are precise, quantitative, and "
    "never invent numbers that are not in the data. Respond with ONLY valid JSON "
    "(no markdown fences, no prose)."
)


def _data_context(analysis, bench_table) -> str:
    """Compact, JSON-serialisable snapshot of the analytics for the prompt."""
    return json.dumps(
        {"analysis": analysis, "benchmark_table": bench_table},
        default=str,
        ensure_ascii=False,
    )


def _llm_insights(analysis, bench_table) -> Optional[List[Dict[str, str]]]:
    prompt = (
        "Using the analytics JSON below, produce the TOP 5 strategic insights, "
        "ordered most to least important. Each insight must be grounded in the "
        "actual figures (cite WoW %, gaps, trends where relevant).\n\n"
        "Return a JSON array of exactly up to 5 objects, each with string fields:\n"
        '  "what"        - the observation (what happened, with numbers)\n'
        '  "why"         - the likely driver / business reason\n'
        '  "implication" - the strategic implication for ZaloPay\n\n'
        "Return ONLY the JSON array.\n\n"
        f"ANALYTICS DATA:\n{_data_context(analysis, bench_table)}"
    )
    parsed = llm_client.chat_json(
        [{"role": "system", "content": _ANALYST_SYSTEM},
         {"role": "user", "content": prompt}],
        max_tokens=6000,
    )
    if not isinstance(parsed, list):
        return None
    cleaned = []
    for item in parsed:
        if isinstance(item, dict) and all(k in item for k in ("what", "why", "implication")):
            cleaned.append({
                "what": str(item["what"]),
                "why": str(item["why"]),
                "implication": str(item["implication"]),
            })
    return cleaned[:5] if cleaned else None


def _llm_recommendations(analysis, bench_table) -> Optional[Dict[str, List[str]]]:
    prompt = (
        "Using the analytics JSON below, produce concrete, actionable "
        "recommendations grouped by team. Each recommendation must be specific "
        "and tied to the data.\n\n"
        "Return a JSON object with exactly these keys, each a list of short "
        "action strings:\n"
        '  "Product"   - up to 4 actions\n'
        '  "Marketing" - up to 3 actions\n'
        '  "CRM"       - up to 4 actions\n\n'
        "Return ONLY the JSON object.\n\n"
        f"ANALYTICS DATA:\n{_data_context(analysis, bench_table)}"
    )
    parsed = llm_client.chat_json(
        [{"role": "system", "content": _ANALYST_SYSTEM},
         {"role": "user", "content": prompt}],
        max_tokens=6000,
    )
    if not isinstance(parsed, dict):
        return None
    result = {}
    caps = {"Product": 4, "Marketing": 3, "CRM": 4}
    for team, cap in caps.items():
        items = parsed.get(team)
        if isinstance(items, list):
            result[team] = [str(x) for x in items[:cap] if str(x).strip()]
        else:
            result[team] = []
    return result if any(result.values()) else None


# ─────────────────────────────────────────────────────────────────────────────
# Public API — LLM first, deterministic rule-based fallback
# ─────────────────────────────────────────────────────────────────────────────

def generate_insights(
    analysis:    Dict[str, Dict[str, Any]],
    bench_table: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Top-5 insights. Generated by the LLM (Qwen); falls back to rules."""
    if llm_client.is_configured():
        try:
            result = _llm_insights(analysis, bench_table)
            if result:
                logger.info("Insights generated by LLM (%d).", len(result))
                return result
            logger.warning("LLM insights unusable — falling back to rules.")
        except Exception:  # noqa: BLE001
            logger.exception("LLM insight generation errored — falling back to rules.")
    return _rule_based_insights(analysis, bench_table)


def generate_recommendations(
    analysis:    Dict[str, Dict[str, Any]],
    bench_table: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Team recommendations. Generated by the LLM (Qwen); falls back to rules."""
    if llm_client.is_configured():
        try:
            result = _llm_recommendations(analysis, bench_table)
            if result:
                logger.info("Recommendations generated by LLM.")
                return result
            logger.warning("LLM recommendations unusable — falling back to rules.")
        except Exception:  # noqa: BLE001
            logger.exception("LLM recommendation generation errored — falling back to rules.")
    return _rule_based_recommendations(analysis, bench_table)
