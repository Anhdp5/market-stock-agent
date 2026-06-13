"""
Report Builder
===============
Assembles all analytical outputs into a polished HTML executive report
and a plain-text version for email body.
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


def _fmt(val: Optional[float], unit: str = "", decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    if unit == "B":
        return f"{val/1e9:.{decimals}f}B"
    if unit == "M":
        return f"{val/1e6:.{decimals}f}M"
    if unit == "%":
        sign = "+" if val >= 0 else ""
        return f"{sign}{val:.{decimals}f}%"
    return f"{val:,.{decimals}f}"


def _arrow(pct: Optional[float]) -> str:
    if pct is None: return "–"
    if pct > 0:     return f"▲ {pct:+.1f}%"
    if pct < 0:     return f"▼ {pct:+.1f}%"
    return f"→ {pct:+.1f}%"


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
    color = colors.get(asmt, "#6b7280")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:12px;font-weight:600;">{asmt}</span>'
    )


def build_html_report(
    report_date:  date,
    analysis:     Dict[str, Dict[str, Any]],
    bench_table:  List[Dict[str, Any]],
    insights:     List[Dict[str, str]],
    recommendations: Dict[str, List[str]],
) -> str:
    """Generate a full HTML email report string."""

    # ── Executive Summary bullets ──────────────────────────────────────────
    mkt_vol  = analysis.get("MarketVolume", {})
    mkt_tx   = analysis.get("MarketTransaction", {})
    zlp_tx   = analysis.get("ZLPTradingTransaction", {})
    zlp_vol  = analysis.get("ZLPTradingVolume", {})
    zlp_na   = analysis.get("ZLPNewAccount", {})
    zlp_au   = analysis.get("ZLPActiveUsers", {})

    tx_bench  = next((r for r in bench_table if r.get("mkt_key") == "MarketTransaction"), {})
    vol_bench = next((r for r in bench_table if r.get("mkt_key") == "MarketVolume"), {})

    exec_bullets = []
    if mkt_vol.get("d0_vs_d1_pct") is not None:
        exec_bullets.append(
            f"Market trading volume {_arrow(mkt_vol['d0_vs_d1_pct'])} DoD; "
            f"7-day trend is <b>{mkt_vol.get('trend','N/A')}</b>."
        )
    if vol_bench.get("assessment") != "N/A":
        gap = vol_bench.get('gap_pp')
        asmt = vol_bench.get('assessment')
        gap_str = f" ({gap:+.1f} pp)" if gap is not None else ""
        exec_bullets.append(
            f"ZaloPay trading value <b>{asmt}</b> vs market{gap_str} on a WoW basis."
        )
    if zlp_na.get("wow_pct") is not None:
        exec_bullets.append(
            f"New account openings: <b>{_arrow(zlp_na['wow_pct'])} WoW</b> — "
            f"trend {zlp_na.get('trend','N/A')}."
        )
    if zlp_au.get("d0") is not None:
        exec_bullets.append(
            f"ZaloPay active users: <b>{_fmt(zlp_au['d0'], 'M', 2)}</b> "
            f"(WoW {_arrow(zlp_au.get('wow_pct'))})."
        )
    if not exec_bullets:
        exec_bullets.append("Insufficient data for full executive summary today.")

    exec_html = "".join(f"<li>{b}</li>" for b in exec_bullets)

    # ── Benchmark table rows ───────────────────────────────────────────────
    bench_rows_html = ""
    for row in bench_table:
        mkt_g = _arrow(row.get("market_growth_pct"))
        zlp_g = _arrow(row.get("zlp_growth_pct")) if row.get("zlp_growth_pct") is not None else "–"
        gap   = f"{row['gap_pp']:+.1f} pp" if row.get("gap_pp") is not None else "–"
        asmt  = _assessment_badge(row.get("assessment", "N/A"))

        bench_rows_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{row['metric_label']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">{mkt_g}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">{zlp_g}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">{gap}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">{asmt}</td>
        </tr>"""

    # ── Insight blocks ─────────────────────────────────────────────────────
    insights_html = ""
    for i, ins in enumerate(insights, 1):
        insights_html += f"""
        <div style="margin-bottom:16px;padding:14px;background:#f8fafc;
                    border-left:4px solid #1e40af;border-radius:4px;">
          <p style="margin:0 0 4px;font-weight:600;color:#1e3a8a;">
            {i}. {ins['what']}
          </p>
          <p style="margin:0 0 4px;color:#374151;">
            <b>Why:</b> {ins['why']}
          </p>
          <p style="margin:0;color:#374151;">
            <b>Implication:</b> {ins['implication']}
          </p>
        </div>"""

    # ── Recommendation blocks ──────────────────────────────────────────────
    rec_colors = {"Product": "#7c3aed", "Marketing": "#b45309", "CRM": "#0f766e"}
    rec_html = ""
    for team, items in recommendations.items():
        color = rec_colors.get(team, "#374151")
        items_html = "".join(f"<li style='margin-bottom:6px;'>{item}</li>" for item in items)
        rec_html += f"""
        <div style="margin-bottom:20px;">
          <h4 style="margin:0 0 8px;color:{color};font-size:14px;text-transform:uppercase;
                     letter-spacing:0.05em;">{team}</h4>
          <ul style="margin:0;padding-left:20px;color:#374151;font-size:14px;">
            {items_html}
          </ul>
        </div>"""

    # ── ZLP metric summary cards ───────────────────────────────────────────
    def metric_card(title, stats, unit=""):
        d0    = _fmt(stats.get("d0"), unit)
        d1pct = _arrow(stats.get("d0_vs_d1_pct"))
        wow   = _arrow(stats.get("wow_pct"))
        trend = stats.get("trend", "N/A")
        trend_color = "#16a34a" if trend == "up" else ("#dc2626" if trend == "down" else "#6b7280")
        return f"""
        <td style="padding:12px;background:#f9fafb;border-radius:6px;
                   border:1px solid #e5e7eb;vertical-align:top;min-width:140px;">
          <div style="font-size:11px;color:#6b7280;font-weight:600;
                      text-transform:uppercase;margin-bottom:4px;">{title}</div>
          <div style="font-size:20px;font-weight:700;color:#111827;margin-bottom:2px;">{d0}</div>
          <div style="font-size:12px;color:#374151;">DoD: {d1pct}</div>
          <div style="font-size:12px;color:#374151;">WoW: {wow}</div>
          <div style="font-size:12px;color:{trend_color};font-weight:600;">
            Trend: {trend}
          </div>
        </td>"""

    zlp_cards = (
        metric_card("New Accounts",    zlp_na) +
        metric_card("Orders (ZLP)",    zlp_tx) +
        metric_card("Trading Value",   zlp_vol, "B") +
        metric_card("Active Users",    zlp_au, "M")
    )
    mkt_cards = (
        metric_card("Mkt Volume",   mkt_vol, "M") +
        metric_card("Mkt Orders",   mkt_tx)
    )

    # ── Full HTML ──────────────────────────────────────────────────────────
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

  <table width="640" cellpadding="0" cellspacing="0"
         style="background:#ffffff;border-radius:8px;
                box-shadow:0 1px 3px rgba(0,0,0,.1);">

    <!-- HEADER -->
    <tr>
      <td style="background:#1e3a8a;padding:24px 32px;border-radius:8px 8px 0 0;">
        <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700;">
          📊 Daily Market Intelligence
        </h1>
        <p style="margin:4px 0 0;color:#93c5fd;font-size:14px;">
          Market vs ZaloPay Stock Performance · {report_date.strftime("%A, %d %B %Y")}
        </p>
      </td>
    </tr>

    <!-- EXECUTIVE SUMMARY -->
    <tr>
      <td style="padding:24px 32px 16px;">
        <h2 style="margin:0 0 12px;font-size:16px;color:#1e3a8a;
                   border-bottom:2px solid #e0e7ff;padding-bottom:8px;">
          Executive Summary
        </h2>
        <ul style="margin:0;padding-left:20px;color:#374151;
                   font-size:14px;line-height:1.7;">
          {exec_html}
        </ul>
      </td>
    </tr>

    <!-- MARKET OVERVIEW -->
    <tr>
      <td style="padding:8px 32px 16px;">
        <h2 style="margin:0 0 12px;font-size:16px;color:#1e3a8a;
                   border-bottom:2px solid #e0e7ff;padding-bottom:8px;">
          Market Overview (HOSE)
        </h2>
        <table cellpadding="4" cellspacing="8" style="border-collapse:separate;
               border-spacing:8px 0;">
          <tr>{mkt_cards}</tr>
        </table>
      </td>
    </tr>

    <!-- ZLP PERFORMANCE -->
    <tr>
      <td style="padding:8px 32px 16px;">
        <h2 style="margin:0 0 12px;font-size:16px;color:#1e3a8a;
                   border-bottom:2px solid #e0e7ff;padding-bottom:8px;">
          ZaloPay Performance
        </h2>
        <table cellpadding="4" cellspacing="8" style="border-collapse:separate;
               border-spacing:8px 0;">
          <tr>{zlp_cards}</tr>
        </table>
      </td>
    </tr>

    <!-- BENCHMARK TABLE -->
    <tr>
      <td style="padding:8px 32px 16px;">
        <h2 style="margin:0 0 12px;font-size:16px;color:#1e3a8a;
                   border-bottom:2px solid #e0e7ff;padding-bottom:8px;">
          Market vs ZaloPay Benchmark (WoW)
        </h2>
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#eff6ff;">
              <th style="padding:8px 12px;text-align:left;color:#1e3a8a;
                         font-weight:600;">Metric</th>
              <th style="padding:8px 12px;text-align:center;color:#1e3a8a;
                         font-weight:600;">Market Growth</th>
              <th style="padding:8px 12px;text-align:center;color:#1e3a8a;
                         font-weight:600;">ZLP Growth</th>
              <th style="padding:8px 12px;text-align:center;color:#1e3a8a;
                         font-weight:600;">Gap</th>
              <th style="padding:8px 12px;text-align:center;color:#1e3a8a;
                         font-weight:600;">Assessment</th>
            </tr>
          </thead>
          <tbody>
            {bench_rows_html}
          </tbody>
        </table>
      </td>
    </tr>

    <!-- KEY INSIGHTS -->
    <tr>
      <td style="padding:8px 32px 16px;">
        <h2 style="margin:0 0 12px;font-size:16px;color:#1e3a8a;
                   border-bottom:2px solid #e0e7ff;padding-bottom:8px;">
          Key Insights
        </h2>
        {insights_html if insights_html else
         '<p style="color:#6b7280;font-size:14px;">Insufficient data for insights today.</p>'}
      </td>
    </tr>

    <!-- RECOMMENDED ACTIONS -->
    <tr>
      <td style="padding:8px 32px 24px;">
        <h2 style="margin:0 0 12px;font-size:16px;color:#1e3a8a;
                   border-bottom:2px solid #e0e7ff;padding-bottom:8px;">
          Recommended Actions
        </h2>
        {rec_html}
      </td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td style="padding:16px 32px;background:#f8fafc;
                 border-top:1px solid #e5e7eb;border-radius:0 0 8px 8px;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-align:center;">
          Generated automatically by ZaloPay Stock Intelligence Agent ·
          {report_date} · Data sources: CafeF (HOSE) · Outlook / DNSE Metabase
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
    """Save the HTML report to disk and return the path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"report_{report_date.strftime('%Y-%m-%d')}.html"
    path = REPORTS_DIR / filename
    path.write_text(html, encoding="utf-8")
    logger.info(f"Report saved: {path}")
    return path


def build_plain_text_summary(
    report_date:  date,
    analysis:     Dict[str, Dict[str, Any]],
    bench_table:  List[Dict[str, Any]],
    insights:     List[Dict[str, str]],
    recommendations: Dict[str, List[str]],
) -> str:
    """Build a compact plain-text version of the report for email fallback."""
    lines = [
        f"[Daily Market Intelligence] Market vs ZaloPay Stock — {report_date}",
        "=" * 65,
        "",
        "EXECUTIVE SUMMARY",
        "-" * 30,
    ]

    for row in bench_table:
        mkt_g = f"{row['market_growth_pct']:+.1f}%" if row.get("market_growth_pct") is not None else "N/A"
        zlp_g = f"{row['zlp_growth_pct']:+.1f}%"    if row.get("zlp_growth_pct")    is not None else "N/A"
        gap   = f"{row['gap_pp']:+.1f} pp"           if row.get("gap_pp")            is not None else "–"
        lines.append(
            f"  {row['metric_label']:<30} Mkt: {mkt_g:>7}  ZLP: {zlp_g:>7}  "
            f"Gap: {gap:>7}  [{row['assessment']}]"
        )

    lines += ["", "KEY INSIGHTS", "-" * 30]
    for i, ins in enumerate(insights, 1):
        lines.append(f"{i}. {ins['what']}")
        lines.append(f"   Why: {ins['why']}")
        lines.append(f"   Action: {ins['implication']}")
        lines.append("")

    lines += ["RECOMMENDED ACTIONS", "-" * 30]
    for team, items in recommendations.items():
        lines.append(f"[{team.upper()}]")
        for item in items:
            lines.append(f"  • {item}")
        lines.append("")

    lines.append(f"─ ZaloPay Stock Intelligence Agent · {report_date} ─")
    return "\n".join(lines)
