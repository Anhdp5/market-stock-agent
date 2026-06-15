"""
ZLP Data Parser
================
Reads ALL *.msg files from data/mock_data/ and extracts ZLP metrics.
Metric names match user-confirmed labels:

  ZLPTransaction          - Daily orders (sum of GTGD segment buckets)
  ZLPValue                - Daily GTGD trading value (B VND), estimated as
                            sum(orders_in_bucket x bucket_value_midpoint).
                            The email's GTGD-by-day metric is chart-only, so we
                            derive value from the value-range segment table.
  ZLPNewAccount           - Daily new accounts opened (filter: ACTIVE statuses)
  ZLPActiveUsers          - Daily active user count
  ZLPActiveSellUsers      - Daily active sell user count   (for Buy/Sell viz)
  ZLPActiveBuyUsers       - Daily active buy user count    (for Buy/Sell viz)
  ZLPActiveUsersMonthly   - Monthly active user trend
  ZLPTransactionBySegment - Daily orders per GTGD bucket (< 100k … >= 10m)

Source tables in each .msg file (confirmed from data1.msg):
  Table with headers [Ngày, 1. < 100k, ..., 8. >= 10m]     → ZLPTransaction + Segment
  Table with headers [Ngày, ative sell user, ..., active user] → Active Users daily
  Table with headers [Tháng, new user, recurring user, active user, ...] → Active Users monthly
  Table with headers [created_date, status, count]           → New Accounts
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import logging
import re
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

MSG_DIR  = config.BASE_DIR / "data" / "mock_data"
MSG_PATH = MSG_DIR / "data1.msg"   # kept for backward compat


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _to_float(val) -> Optional[float]:
    """Vietnamese number: '2.385' (thousands sep) → 2385.0"""
    try:
        v = str(val).strip().replace(" ", "").replace("\xa0", "")
        if not v or v in ("-", "—", "N/A", ""):
            return None
        v = v.replace(".", "").replace(",", ".")
        return float(v)
    except Exception:
        return None


def _num_with_suffix(tok: str) -> Optional[float]:
    """'100k'->100000, '10m'->10000000, '500'->500."""
    tok = tok.strip().lower().replace(",", "").replace(" ", "")
    if not tok:
        return None
    mult = 1.0
    if tok.endswith("k"):
        mult, tok = 1e3, tok[:-1]
    elif tok.endswith("m"):
        mult, tok = 1e6, tok[:-1]
    try:
        return float(tok) * mult
    except ValueError:
        return None


def _bucket_midpoint(label: str) -> float:
    """
    Estimate the representative GTGD (order value, VND) for a value-range bucket
    label like '1. < 100k', '4. 1m-2m', '8. >= 10m'.
    Open-ended top bucket (>= X) uses 1.5x its lower bound.
    """
    s = re.sub(r"^\s*\d+\.\s*", "", label.strip().lower())
    nums = re.findall(r"[\d.,]+\s*[km]?", s)
    vals = [v for v in (_num_with_suffix(n) for n in nums) if v is not None]
    if "<" in s and vals:
        return vals[0] / 2.0                  # '< 100k' -> 50k
    if (">=" in s or ">" in s) and vals:
        return vals[0] * 1.5                   # '>= 10m' -> 15m
    if len(vals) >= 2:
        return (vals[0] + vals[1]) / 2.0       # '1m-2m' -> 1.5m
    if vals:
        return vals[0]
    return 0.0


def _parse_date(val: str) -> Optional[date]:
    """Parse 'June 8, 2026, 00:00' / 'June 8, 2026' / 'Monday, June 8, 2026' → date"""
    val = re.sub(r"^[A-Za-z]+,\s*", "", val.strip())   # strip weekday prefix
    val = re.sub(r",?\s*00:00.*$", "", val.strip())      # strip time suffix
    for fmt in ("%B %d, %Y", "%d/%m/%Y", "%Y-%m-%d", "%B %d %Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(val.strip()).date()
    except Exception:
        return None


def _table_to_df(tbl_elem) -> pd.DataFrame:
    rows = tbl_elem.find_all("tr")
    if not rows:
        return pd.DataFrame()
    data = []
    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        data.append(cells)
    if len(data) < 2:
        return pd.DataFrame()
    max_cols = max(len(r) for r in data)
    for r in data:
        while len(r) < max_cols:
            r.append("")
    return pd.DataFrame(data[1:], columns=data[0])


def _load_html(msg_path: Path) -> Optional[str]:
    try:
        import extract_msg
        with extract_msg.Message(str(msg_path)) as m:
            html = m.htmlBody or b""
            if isinstance(html, bytes):
                html = html.decode("utf-8", errors="replace")
            return html
    except ImportError:
        logger.error("extract-msg not installed. Run: pip install extract-msg --break-system-packages")
        return None
    except Exception as e:
        logger.error("Failed to open {}: {}".format(msg_path, e))
        return None


# ─── Table matchers ──────────────────────────────────────────────────────────

def _is_segment_table(headers: List[str]) -> bool:
    """Table[79]: Ngày | 1. < 100k | 2. 100k-500k | ... | 8. >= 10m"""
    if any(len(h) > 60 for h in headers):
        return False
    if not headers or headers[0].lower() not in ("ngày", "ngay", "date"):
        return False
    return any("< 100k" in h for h in headers) and any(">= 10m" in h or "10m" in h for h in headers)


def _is_active_users_daily(headers: List[str]) -> bool:
    """Table[73]: Ngày | ative sell user | active buying us... | active user"""
    h = " ".join(headers).lower()
    return (
        headers[0].lower() in ("ngày", "ngay", "date") and
        "active user" in h and
        ("sell user" in h or "buying" in h or "ative" in h) and
        "tháng" not in h and len(headers) <= 6
    )


def _is_active_users_monthly(headers: List[str]) -> bool:
    """Table[75]: Tháng | new user | recurring user | active user | ..."""
    h = " ".join(headers).lower()
    return (
        headers[0].lower() in ("tháng", "thang") and
        "active user" in h and "new user" in h
    )


def _is_new_account_table(headers: List[str]) -> bool:
    """Table[59]: created_date | status | count"""
    return "created_date" in headers and "status" in headers and "count" in headers


# ─── Extractors ──────────────────────────────────────────────────────────────

def _extract_transaction_and_segment(tables) -> Dict[str, Optional[pd.DataFrame]]:
    """
    Table[79]: Ngày | 1. < 100k | ... | 8. >= 10m
    Returns ZLPTransaction (row sum) and ZLPTransactionBySegment (per-bucket).
    """
    for tbl in tables:
        rows = tbl.find_all("tr")
        if not rows:
            continue
        headers = [td.get_text(strip=True) for td in rows[0].find_all(["td", "th"])]
        if not _is_segment_table(headers):
            continue
        df = _table_to_df(tbl)
        if df.empty:
            continue
        date_col  = df.columns[0]
        val_cols  = list(df.columns[1:])
        midpoints = {c: _bucket_midpoint(c) for c in val_cols}
        tx_records  = []
        seg_records = []
        val_records = []
        for _, row in df.iterrows():
            d = _parse_date(str(row[date_col]))
            if not d:
                continue
            buckets = {c: (_to_float(str(row[c])) or 0.0) for c in val_cols}
            total = sum(buckets.values())
            tx_records.append({"date": d, "ZLPTransaction": total})
            # GTGD trading value (B VND) = sum(orders in bucket x bucket midpoint)
            value_vnd = sum(buckets[c] * midpoints[c] for c in val_cols)
            val_records.append({"date": d, "ZLPValue": value_vnd / 1e9})
            seg_row = {"date": d}
            seg_row.update(buckets)
            seg_records.append(seg_row)
        if tx_records:
            tx_df  = pd.DataFrame(tx_records).drop_duplicates("date").sort_values("date")
            seg_df = pd.DataFrame(seg_records).drop_duplicates("date").sort_values("date")
            val_df = pd.DataFrame(val_records).drop_duplicates("date").sort_values("date")
            logger.info("[ZLPTransaction] {} rows (from segment table sum)".format(len(tx_df)))
            logger.info("[ZLPValue] {} rows (GTGD est. from value buckets, B VND)".format(len(val_df)))
            return {"ZLPTransaction": tx_df, "ZLPTransactionBySegment": seg_df,
                    "ZLPValue": val_df}
    return {}


def _extract_active_users_daily(tables) -> Dict[str, Optional[pd.DataFrame]]:
    """
    Table[73]: Ngày | ative sell user | active buying us... | active user
    Returns ZLPActiveUsers, ZLPActiveSellUsers, ZLPActiveBuyUsers.
    """
    for tbl in tables:
        rows = tbl.find_all("tr")
        if not rows:
            continue
        headers = [td.get_text(strip=True) for td in rows[0].find_all(["td", "th"])]
        if not headers or any(len(h) > 60 for h in headers):
            continue
        if not _is_active_users_daily(headers):
            continue
        df = _table_to_df(tbl)
        if df.empty:
            continue
        date_col = df.columns[0]
        # Identify columns by keyword
        sell_col = next((c for c in df.columns if "sell" in c.lower()), None)
        buy_col  = next((c for c in df.columns if "buy" in c.lower() or "buying" in c.lower()), None)
        act_col  = next((c for c in df.columns if c.lower().strip() in ("active user", "active users")), None)
        if not act_col:
            act_col = next((c for c in df.columns if "active" in c.lower() and "sell" not in c.lower() and "buy" not in c.lower() and "ative" not in c.lower()), None)
        if not act_col:
            # last column is usually total active user
            act_col = df.columns[-1]

        records = {"ZLPActiveUsers": [], "ZLPActiveSellUsers": [], "ZLPActiveBuyUsers": []}
        for _, row in df.iterrows():
            d = _parse_date(str(row[date_col]))
            if not d:
                continue
            au  = _to_float(str(row[act_col]))
            asl = _to_float(str(row[sell_col])) if sell_col else None
            abl = _to_float(str(row[buy_col]))  if buy_col  else None
            if au  is not None: records["ZLPActiveUsers"].append({"date": d, "ZLPActiveUsers": au})
            if asl is not None: records["ZLPActiveSellUsers"].append({"date": d, "ZLPActiveSellUsers": asl})
            if abl is not None: records["ZLPActiveBuyUsers"].append({"date": d, "ZLPActiveBuyUsers": abl})

        result = {}
        for key, recs in records.items():
            if recs:
                result[key] = pd.DataFrame(recs).drop_duplicates("date").sort_values("date")
                logger.info("[{}] {} rows".format(key, len(result[key])))
        if result:
            return result
    return {}


def _extract_active_users_monthly(tables) -> Optional[pd.DataFrame]:
    """
    Table[75]: Tháng | new user | recurring user | active user | ...
    Returns ZLPActiveUsersMonthly.
    """
    for tbl in tables:
        rows = tbl.find_all("tr")
        if not rows:
            continue
        headers = [td.get_text(strip=True) for td in rows[0].find_all(["td", "th"])]
        if not headers or not _is_active_users_monthly(headers):
            continue
        df = _table_to_df(tbl)
        if df.empty:
            continue
        date_col = df.columns[0]
        active_col = next(
            (c for c in df.columns
             if c.strip().lower() == "active user" and
             "sell" not in c.lower() and "buy" not in c.lower()),
            None
        )
        if not active_col:
            continue
        records = []
        for _, row in df.iterrows():
            d = _parse_date(str(row[date_col]))
            v = _to_float(str(row[active_col]))
            if d and v:
                records.append({"date": d, "ZLPActiveUsersMonthly": v})
        if records:
            result = pd.DataFrame(records).drop_duplicates("date").sort_values("date")
            logger.info("[ZLPActiveUsersMonthly] {} rows".format(len(result)))
            return result
    return None


def _extract_new_account(tables) -> Optional[pd.DataFrame]:
    """
    Table[59]: created_date | status | count
    Filter: ACTIVE statuses only.
    Returns ZLPNewAccount.
    """
    ACTIVE_STATUSES = {"CORE_ACTIVE", "ACTIVE", "SUBMITTED", "APPROVED", "VSD_ACTIVE"}
    for tbl in tables:
        rows = tbl.find_all("tr")
        if not rows:
            continue
        headers = [td.get_text(strip=True) for td in rows[0].find_all(["td", "th"])]
        if not _is_new_account_table(headers):
            continue
        df = _table_to_df(tbl)
        if df.empty:
            continue
        totals: Dict = {}
        for _, row in df.iterrows():
            d      = _parse_date(str(row.get("created_date", "")))
            status = str(row.get("status", "")).upper().strip()
            v      = _to_float(str(row.get("count", "0"))) or 0.0
            if d and status in ACTIVE_STATUSES:
                totals[d] = totals.get(d, 0.0) + v
        if totals:
            result = pd.DataFrame(
                [{"date": d, "ZLPNewAccount": v} for d, v in totals.items()]
            ).sort_values("date")
            logger.info("[ZLPNewAccount] {} rows".format(len(result)))
            return result
    return None


# ─── Main entry ──────────────────────────────────────────────────────────────

def collect_zlp_data(
    since_days: int = 35,
    msg_path: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Parse all .msg files in data/mock_data/ (or a single file if msg_path given).
    Returns dict: metric_key → DataFrame(date, <metric_key>)
    """
    # Determine which files to read
    if msg_path:
        paths = [Path(msg_path)]
    else:
        paths = sorted(MSG_DIR.glob("data*.msg"))

    if not paths:
        logger.error("No .msg files found in {}".format(MSG_DIR))
        return {}

    logger.info("Loading ZLP data from {} file(s)".format(len(paths)))

    # Accumulate per-metric DataFrames across all files
    combined: Dict[str, List[pd.DataFrame]] = {}

    for p in paths:
        if not p.exists():
            logger.warning("Missing: {}".format(p))
            continue
        html = _load_html(p)
        if not html:
            continue
        soup   = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")
        logger.info("[{}] {} tables".format(p.name, len(tables)))

        # ZLP Transaction + Segment
        ts = _extract_transaction_and_segment(tables)
        for k, df in ts.items():
            if df is not None and not df.empty:
                combined.setdefault(k, []).append(df)

        # Active users daily (+ sell/buy breakdown)
        au = _extract_active_users_daily(tables)
        for k, df in au.items():
            if df is not None and not df.empty:
                combined.setdefault(k, []).append(df)

        # Active users monthly (from any file, latest wins)
        aum = _extract_active_users_monthly(tables)
        if aum is not None and not aum.empty:
            combined.setdefault("ZLPActiveUsersMonthly", []).append(aum)

        # New accounts
        na = _extract_new_account(tables)
        if na is not None and not na.empty:
            combined.setdefault("ZLPNewAccount", []).append(na)

    # Merge all files: concatenate, keep latest value per date
    results: Dict[str, pd.DataFrame] = {}
    for key, dfs in combined.items():
        merged = pd.concat(dfs, ignore_index=True)
        # For duplicate dates across files, keep the last (most recent file)
        merged = merged.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
        results[key] = merged
        logger.info("[{}] final: {} rows ({} to {})".format(
            key, len(merged),
            merged["date"].min(), merged["date"].max()
        ))

    logger.info("ZLP data ready: {}".format(
        ", ".join("{}({})".format(k, len(v)) for k, v in results.items())
    ))
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    data = collect_zlp_data()
    for key, df in data.items():
        print("\n-- {} --".format(key))
        print(df.to_string(index=False))
