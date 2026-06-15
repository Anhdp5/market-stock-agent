"""
Report Builder
===============
Assembles analytical outputs into an HTML executive report.

Sections:
  1. Executive Summary   — answers 3 strategic questions
  2. Market Overview     — HOSE metrics + Buy/Sell pressure bar
  3. ZaloPay Performance — ZLP metrics + Active Buy/Sell user bar
  4. WoW Benchmark       — Market vs ZLP comparison table
  5. Key Insights        — Ranked insight cards (what / why / implication)
  6. Recommended Actions — Team-grouped action list
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging
from datetime import date
from pathlib import Path
from typing import Dict, Any, List, Optional

import config

logger = logging.getLogger(__name__)

REPORTS_DIR = config.REPORTS_DIR


# ─── Formatters ──────────────────────────────────────────────────────────────

def _fmt(val: Optional[float], unit: str = "", decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    if unit == "B":
        return f"{val:.{decimals}f}B"
    if unit == "M":
        return f"{val/1e6:.{decimals}f}M"
    if unit == "K":
        return f"{val/1e3:.{decimals}f}K"
    if unit == "%":
        sign = "+" if val >= 0 else ""
        return f"{sign}{val:.{decimals}f}%"
    if val >= 1_000_000:
        return f"{val/1_000_000:.{decimals}f}M"
    if val >= 1_000:
        return f"{val/1_000:.{decimals}f}K"
    return f"{val:,.{decimals}f}"


def _arrow(pct: Optional[float], decimals: int = 1) -> str:
    if pct is None:
        return "–"
    if pct > 0:
        return f'<span style="color:#16a34a;">▲ {pct:+.{decimals}f}%</span>'
    if pct < 0:
        return f'<span style="color:#dc2626;">▼ {pct:+.{decimals}f}%</span>'
    return f'<span style="color:#6b7280;">→ {pct:+.{decimals}f}%</span>'


def _arrow_text(pct: Optional[float]) -> str:
    if pct is None:
        return "–"
    return f"{'▲' if pct > 0 else ('▼' if pct < 0 else '→')} {pct:+.1f}%"


def _badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:11px;font-weight:700;">{text}</span>'
    )


def _assessment_badge(asmt: str) -> str:
    colors = {
        "Outperform":   "#16a34a",
        "Improving":    "#16a34a",
        "In Line":      "#d97706",
        "Stable":       "#d97706",
        "Underperform": "#dc2626",
        "Declining":    "#dc2626",
        "N/A":          "#6b7280",
    }
    return _badge(asmt, colors.get(asmt, "#6b7280"))


def _trend_badge(trend: str) -> str:
    colors = {"up": "#16a34a", "down": "#dc2626", "flat": "#d97706"}
    symbols = {"up": "↑", "down": "↓", "flat": "→"}
    color  = colors.get(trend, "#9ca3af")
    symbol = symbols.get(trend, "?")
    return f'<span style="color:{color};font-weight:700;">{symbol} {trend}</span>'


# ─── Metric card ─────────────────────────────────────────────────────────────

def _metric_card(title: str, stats: Dict[str, Any], unit: str = "") -> str:
    d0    = _fmt(stats.get("d0"), unit)
    d1pct = _arrow(stats.get("d0_vs_d1_pct"))
    wow   = _arrow(stats.get("wow_pct"))
    trend = stats.get("trend", "N/A")
    trend_color = "#16a34a" if trend == "up" else ("#dc2626" if trend == "down" else "#6b7280")
    avail = stats.get("available_days", 0)
    avail_note = "" if avail >= 5 else f'<div style="font-size:10px;color:#f59e0b;">⚠ {avail}d data</div>'
    return f"""
    <td style="padding:12px;background:#f9fafb;border-radius:6px;
               border:1px solid #e5e7eb;vertical-align:top;min-width:130px;">
      <div style="font-size:11px;color:#6b7280;font-weight:600;
                  text-transform:uppercase;margin-bottom:4px;">{title}</div>
      <div style="font-size:18px;font-weight:700;color:#111827;margin-bottom:2px;">{d0}</div>
      <div style="font-size:12px;color:#374151;margin-bottom:1px;">DoD: {d1pct}</div>
      <div style="font-size:12px;color:#374151;margin-bottom:1px;">WoW: {wow}</div>
      <div style="font-size:12px;color:{trend_color};font-weight:600;">
        Trend: {trend}
      </div>
      {avail_note}
    </td>"""


# ─── Buy/Sell pressure bar ────────────────────────────────────────────────────

def _buy_sell_bar(buy_val: Optional[float], sell_val: Optional[float],
                  buy_label: str = "Buy", sell_label: str = "Sell") -> str:
    """Horizontal stacked bar showing buy vs sell ratio."""
    if buy_val is None or sell_val is None or (buy_val + sell_val) == 0:
        return '<p style="color:#6b7280;font-size:13px;">Buy/Sell data not available.</p>'
    total = buy_val + sell_val
    buy_pct  = buy_val  / total * 100
    sell_pct = sell_val / total * 100
    return f"""
    <div style="margin-top:12px;">
      <div style="font-size:12px;color:#6b7280;margin-bottom:4px;font-weight:600;">
        BUY / SELL PRESSURE
      </div>
      <div style="display:flex;height:20px;border-radius:4px;overflow:hidden;">
        <div style="width:{buy_pct:.1f}%;background:#16a34a;"></div>
        <div style="width:{sell_pct:.1f}%;background:#dc2626;"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:12px;
                  margin-top:4px;color:#374151;">
        <span style="color:#16a34a;font-weight:600;">
          {buy_label}: {_fmt(buy_val)} ({buy_pct:.1f}%)
        </span>
        <span style="color:#dc2626;font-weight:600;">
          {sell_label}: {_fmt(sell_val)} ({sell_pct:.1f}%)
        </span>
      </div>
    </div>"""


# ─── Section builders ────────────────────────────────────────────────────────

def _section_header(title: str) -> str:
    return f"""
    <h2 style="margin:0 0 14px;font-size:16px;color:#1e3a8a;
               border-bottom:2px solid #e0e7ff;padding-bottom:8px;">{title}</h2>"""


def _build_exec_summary(
    analysis:    Dict[str, Dict[str, Any]],
    bench_table: List[Dict[str, Any]],
) -> str:
    """
    Answers 3 strategic questions:
      Q1: Is ZLP faster or slower than the market this week?
      Q2: Is performance market-driven or internal (ZLP-specific)?
      Q3: Which ZLP metrics are outperforming vs underperforming?
    """
    mkt_vol = analysis.get("MarketVolume", {})
    zlp_tx  = analysis.get("ZLPTransaction", {})
    zlp_au  = analysis.get("ZLPActiveUsers", {})
    zlp_na  = analysis.get("ZLPNewAccount", {})

    tx_bench = next((r for r in bench_table if r.get("zlp_key") == "ZLPTransaction"), {})

    # Q1: ZLP vs market speed
    mkt_wow = mkt_vol.get("wow_pct")
    zlp_wow = zlp_tx.get("wow_pct")
    if mkt_wow is not None and zlp_wow is not None:
        gap = zlp_wow - mkt_wow
        if gap > 2:
            q1 = (f"ZaloPay is <b>outpacing the market</b>: ZLP orders "
                  f"{_arrow_text(zlp_wow)} WoW vs market volume {_arrow_text(mkt_wow)} "
                  f"(+{gap:.1f} pp advantage).")
        elif gap < -2:
            q1 = (f"ZaloPay is <b>lagging the market</b>: ZLP orders "
                  f"{_arrow_text(zlp_wow)} WoW vs market volume {_arrow_text(mkt_wow)} "
                  f"({gap:.1f} pp gap).")
        else:
            q1 = (f"ZaloPay is <b>tracking the market</b>: ZLP orders "
                  f"{_arrow_text(zlp_wow)} WoW, market {_arrow_text(mkt_wow)} "
                  f"({gap:+.1f} pp — broadly in line).")
    elif mkt_wow is not None:
        q1 = (f"Market volume {_arrow_text(mkt_wow)} WoW. "
              "ZLP order data insufficient for comparison.")
    else:
        q1 = "Insufficient WoW data for Market vs ZLP comparison this period."

    # Q2: Market-driven vs internal
    mkt_trend = mkt_vol.get("trend", "insufficient_data")
    au_trend  = zlp_au.get("trend", "insufficient_data")
    if mkt_trend == au_trend and mkt_trend in ("up", "down"):
        direction = "rising" if mkt_trend == "up" else "declining"
        q2 = (f"Both market and ZLP active users are <b>trending {direction}</b>, "
              "suggesting performance is primarily <b>macro-driven</b>. "
              "ZLP is moving with the tide, not against it.")
    elif mkt_trend in ("up", "down") and au_trend not in (mkt_trend, "insufficient_data"):
        q2 = (f"Market is trending <b>{mkt_trend}</b> but ZLP active users are "
              f"trending <b>{au_trend}</b>, indicating <b>platform-specific factors</b> "
              "are diverging from macro conditions — investigate internal drivers.")
    else:
        q2 = "Trend data is limited; cannot definitively separate macro vs platform drivers."

    # Q3: Which metrics outperform / underperform
    outperform = [r["metric_label"] for r in bench_table if r.get("assessment") in ("Outperform", "Improving")]
    underperform = [r["metric_label"] for r in bench_table if r.get("assessment") in ("Underperform", "Declining")]
    stable = [r["metric_label"] for r in bench_table if r.get("assessment") in ("In Line", "Stable")]

    def _join(lst):
        return ", ".join(f"<b>{x}</b>" for x in lst) if lst else "none"

    q3 = (f"Outperforming: {_join(outperform)}. "
          f"Underperforming: {_join(underperform)}. "
          f"In line: {_join(stable)}.")

    bullets = [
        ("Q1 — Speed vs Market", q1),
        ("Q2 — Macro vs Internal", q2),
        ("Q3 — Metric Scorecard", q3),
    ]
    items = ""
    for label, text in bullets:
        items += f"""
        <li style="margin-bottom:10px;">
          <span style="font-weight:700;color:#1e3a8a;">{label}:</span>
          <span style="color:#374151;"> {text}</span>
        </li>"""

    return f"""
    <tr><td style="padding:24px 32px 16px;">
      {_section_header("1. Executive Summary")}
      <ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.7;">
        {items}
      </ul>
    </td></tr>"""


def _build_market_overview(analysis: Dict[str, Dict[str, Any]]) -> str:
    mkt_vol  = analysis.get("MarketVolume",    {})
    mkt_val  = analysis.get("MarketValue",     {})
    buy_vol  = analysis.get("BuyVolume",       {})
    sell_vol = analysis.get("SellVolume",      {})
    ord_cnt  = analysis.get("MarketOrderCount",{})

    cards = (
        _metric_card("Volume (shares)",  mkt_vol) +
        _metric_card("Value (B VND)",    mkt_val, "B") +
        _metric_card("Orders",           ord_cnt)
    )

    buy_sell = _buy_sell_bar(
        buy_vol.get("d0"), sell_vol.get("d0"),
        "Buy Vol", "Sell Vol"
    )

    return f"""
    <tr><td style="padding:8px 32px 16px;">
      {_section_header("2. Market Overview (HOSE)")}
      <table cellpadding="0" cellspacing="0"
             style="border-collapse:separate;border-spacing:8px 0;">
        <tr>{cards}</tr>
      </table>
      {buy_sell}
    </td></tr>"""


def _build_zlp_performance(analysis: Dict[str, Dict[str, Any]]) -> str:
    zlp_na   = analysis.get("ZLPNewAccount",      {})
    zlp_tx   = analysis.get("ZLPTransaction",     {})
    zlp_val  = analysis.get("ZLPValue",           {})
    zlp_au   = analysis.get("ZLPActiveUsers",     {})
    zlp_sell = analysis.get("ZLPActiveSellUsers", {})
    zlp_buy  = analysis.get("ZLPActiveBuyUsers",  {})

    # Order: New Accounts -> Active Users -> Value (B VND) -> Orders
    cards = (
        _metric_card("New Accounts",  zlp_na) +
        _metric_card("Active Users",  zlp_au) +
        _metric_card("Value (B VND)", zlp_val, "B") +
        _metric_card("Orders",        zlp_tx)
    )

    buy_sell = _buy_sell_bar(
        zlp_buy.get("d0"), zlp_sell.get("d0"),
        "Active Buy Users", "Active Sell Users"
    )

    return f"""
    <tr><td style="padding:8px 32px 16px;">
      {_section_header("3. ZaloPay Performance")}
      <table cellpadding="0" cellspacing="0"
             style="border-collapse:separate;border-spacing:8px 0;">
        <tr>{cards}</tr>
      </table>
      {buy_sell}
    </td></tr>"""


def _build_wow_benchmark(bench_table: List[Dict[str, Any]]) -> str:
    if not bench_table:
        return f"""
        <tr><td style="padding:8px 32px 16px;">
          {_section_header("4. WoW Benchmark (Market vs ZaloPay)")}
          <p style="color:#6b7280;font-size:14px;">
            No benchmark data available. Ensure at least 2 weeks of .msg files are loaded.
          </p>
        </td></tr>"""

    rows_html = ""
    for row in bench_table:
        mkt_g = _arrow(row.get("market_growth_pct"))
        zlp_g = _arrow(row.get("zlp_growth_pct")) if row.get("zlp_growth_pct") is not None else "–"
        gap   = f"{row['gap_pp']:+.1f} pp" if row.get("gap_pp") is not None else "–"
        asmt  = _assessment_badge(row.get("assessment", "N/A"))
        narrative = row.get("narrative", "")

        rows_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;
                     font-weight:600;font-size:13px;">{row['metric_label']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;
                     text-align:center;">{mkt_g}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;
                     text-align:center;">{zlp_g}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;
                     text-align:center;">{gap}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;
                     text-align:center;">{asmt}</td>
        </tr>
        <tr>
          <td colspan="5" style="padding:4px 12px 10px;border-bottom:2px solid #e5e7eb;
                                  font-size:12px;color:#6b7280;font-style:italic;">
            {narrative}
          </td>
        </tr>"""

    return f"""
    <tr><td style="padding:8px 32px 16px;">
      {_section_header("4. WoW Benchmark (Market vs ZaloPay)")}
      <p style="font-size:12px;color:#6b7280;margin:0 0 10px;">
        WoW = avg of the last 5 trading days vs the prior 5 trading days
        (a trading week is 5 days; weekends are not traded).
        Gap = ZLP growth − Market growth (positive = ZLP outperforming).
      </p>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#eff6ff;">
            <th style="padding:8px 12px;text-align:left;color:#1e3a8a;">Metric</th>
            <th style="padding:8px 12px;text-align:center;color:#1e3a8a;">Market WoW</th>
            <th style="padding:8px 12px;text-align:center;color:#1e3a8a;">ZLP WoW</th>
            <th style="padding:8px 12px;text-align:center;color:#1e3a8a;">Gap</th>
            <th style="padding:8px 12px;text-align:center;color:#1e3a8a;">Assessment</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </td></tr>"""


def _build_insights(insights: List[Dict[str, str]]) -> str:
    if not insights:
        no_data = """
        <p style="color:#6b7280;font-size:14px;">
          No significant signals detected in the current data window.
          This may indicate insufficient historical data (need ≥2 weeks) or
          stable, in-line performance with no outliers to flag.
        </p>"""
        return f"""
        <tr><td style="padding:8px 32px 16px;">
          {_section_header("5. Key Insights")}
          {no_data}
        </td></tr>"""

    cards = ""
    priority_colors = ["#1e40af", "#7c3aed", "#0f766e", "#b45309", "#374151"]
    for i, ins in enumerate(insights):
        border_color = priority_colors[min(i, len(priority_colors)-1)]
        cards += f"""
        <div style="margin-bottom:14px;padding:14px;background:#f8fafc;
                    border-left:4px solid {border_color};border-radius:4px;">
          <p style="margin:0 0 6px;font-weight:700;color:#111827;font-size:14px;">
            {i+1}. {ins['what']}
          </p>
          <p style="margin:0 0 4px;color:#374151;font-size:13px;">
            <b>Why:</b> {ins['why']}
          </p>
          <p style="margin:0;color:#374151;font-size:13px;">
            <b>Implication:</b> {ins['implication']}
          </p>
        </div>"""

    return f"""
    <tr><td style="padding:8px 32px 16px;">
      {_section_header("5. Key Insights")}
      {cards}
    </td></tr>"""


def _build_recommendations(recommendations: Dict[str, List[str]]) -> str:
    team_styles = {
        "Product":   ("#7c3aed", "🛠"),
        "Marketing": ("#b45309", "📣"),
        "CRM":       ("#0f766e", "🔄"),
    }
    blocks = ""
    for team, items in recommendations.items():
        color, icon = team_styles.get(team, ("#374151", "•"))
        items_html = ""
        for item in items:
            # Detect if item has a diagnostic path hint
            diag_marker = "→" if "→" in item else ""
            item_clean = item.replace("→", "<span style='color:#6b7280;'>→</span>")
            items_html += f"""
            <li style="margin-bottom:8px;font-size:13px;color:#374151;
                       line-height:1.6;">{item_clean}</li>"""
        blocks += f"""
        <div style="margin-bottom:20px;padding:14px;background:#fafafa;
                    border-radius:6px;border:1px solid #e5e7eb;">
          <h4 style="margin:0 0 10px;color:{color};font-size:13px;
                     text-transform:uppercase;letter-spacing:0.06em;
                     font-weight:700;">{icon} {team}</h4>
          <ul style="margin:0;padding-left:18px;">{items_html}</ul>
        </div>"""

    return f"""
    <tr><td style="padding:8px 32px 24px;">
      {_section_header("6. Recommended Actions")}
      {blocks}
    </td></tr>"""


# ─── Main builder ─────────────────────────────────────────────────────────────

def build_html_report(
    report_date:     date,
    analysis:        Dict[str, Dict[str, Any]],
    bench_table:     List[Dict[str, Any]],
    insights:        List[Dict[str, str]],
    recommendations: Dict[str, List[str]],
) -> str:

    exec_section  = _build_exec_summary(analysis, bench_table)
    mkt_section   = _build_market_overview(analysis)
    zlp_section   = _build_zlp_performance(analysis)

    # Data availability note
    avail_days = {k: v.get("available_days", 0) for k, v in analysis.items()}
    max_days   = max(avail_days.values()) if avail_days else 0
    data_note  = (
        f'<span style="color:#16a34a;">✓ {max_days} trading days in analysis window.</span>'
        if max_days >= 10 else
        f'<span style="color:#f59e0b;">⚠ Only {max_days} trading days available. '
        f'WoW benchmarks need ≥10 trading days (two trading weeks) for full accuracy.</span>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Market Intelligence — {report_date}</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f1f5f9">
<tr><td align="center" style="padding:24px 16px;">

  <table width="660" cellpadding="0" cellspacing="0"
         style="background:#ffffff;border-radius:8px;
                box-shadow:0 1px 3px rgba(0,0,0,.1);">

    <!-- HEADER -->
    <tr>
      <td style="background:#1e3a8a;padding:24px 32px;border-radius:8px 8px 0 0;">
        <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700;">
          📊 Daily Market Intelligence
        </h1>
        <p style="margin:6px 0 0;color:#93c5fd;font-size:13px;">
          Market vs ZaloPay Stock Performance ·
          {report_date.strftime("%A, %d %B %Y")}
        </p>
        <p style="margin:4px 0 0;font-size:12px;">{data_note}</p>
      </td>
    </tr>

    {exec_section}
    {mkt_section}
    {zlp_section}

    <!-- FOOTER -->
    <tr>
      <td style="padding:16px 32px;background:#f8fafc;
                 border-top:1px solid #e5e7eb;border-radius:0 0 8px 8px;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-align:center;">
          Generated automatically by ZaloPay Stock Intelligence Agent ·
          {report_date} · Data: CafeF (HOSE) + Metabase email exports
        </p>
      </td>
    </tr>

  </table>
</td></tr>
</table>
</body>
</html>"""

    return html


def save_report(html: str, report_date: date) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"report_{report_date.strftime('%Y-%m-%d')}.html"
    path = REPORTS_DIR / filename
    path.write_text(html, encoding="utf-8")
    logger.info(f"Report saved: {path}")
    return path


def build_plain_text_summary(
    report_date:     date,
    analysis:        Dict[str, Dict[str, Any]],
    bench_table:     List[Dict[str, Any]],
    insights:        List[Dict[str, str]],
    recommendations: Dict[str, List[str]],
) -> str:
    lines = [
        f"[Daily Market Intelligence] Market vs ZaloPay — {report_date}",
        "=" * 65,
        "",
        "EXECUTIVE SUMMARY",
        "-" * 30,
    ]

    mkt_vol = analysis.get("MarketVolume", {})
    zlp_tx  = analysis.get("ZLPTransaction", {})
    if mkt_vol.get("wow_pct") is not None:
        lines.append(f"  Market Volume WoW: {_arrow_text(mkt_vol['wow_pct'])}")
    if zlp_tx.get("wow_pct") is not None:
        lines.append(f"  ZLP Orders WoW:    {_arrow_text(zlp_tx['wow_pct'])}")

    lines += ["", f"─ ZaloPay Stock Intelligence Agent · {report_date} ─"]
    return "\n".join(lines)
