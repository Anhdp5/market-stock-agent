"""
Email Parser — ZaloPay Internal Metrics
=========================================
Reads emails from metabase@mail.dnse.com.vn, matches each email subject
to a ZLP metric key, and extracts tabular data from the HTML body or
attached Excel/CSV file.

Returns a dict keyed by metric name → pandas DataFrame.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import io
import logging
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd
from bs4 import BeautifulSoup

import config
from collector.email_ingestion.graph_client import IMAPClient

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: fuzzy subject matcher
# ─────────────────────────────────────────────────────────────────────────────

def _match_subject(subject: str) -> Optional[str]:
    """
    Match email subject to a ZLP metric key.
    Returns the internal metric key (e.g. 'ZLPNewAccount') or None.
    """
    subject_lower = subject.lower()
    for email_subject, metric_key in config.ZLP_EMAIL_METRICS.items():
        # Check if the key words from the configured subject appear in the email subject
        keywords = [w.lower() for w in email_subject.split() if len(w) > 3]
        if sum(1 for kw in keywords if kw in subject_lower) >= max(2, len(keywords) // 2):
            return metric_key

    # Hard fallbacks for common Vietnamese abbreviations
    if "tài khoản" in subject_lower and ("mở" in subject_lower or "zlp" in subject_lower):
        return "ZLPNewAccount"
    if "lệnh khớp" in subject_lower and "nhóm" in subject_lower:
        return "ZLPTransactionbyusersegment"
    if "lệnh khớp" in subject_lower:
        return "ZLPTradingTransaction"
    if "gtgd" in subject_lower or "giá trị" in subject_lower:
        return "ZLPTradingVolume"
    if "active" in subject_lower or "kh active" in subject_lower:
        return "ZLPActiveUsers"

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Helper: extract table from HTML email body
# ─────────────────────────────────────────────────────────────────────────────

def _extract_table_from_html(html: str) -> Optional[pd.DataFrame]:
    """Parse the first meaningful table from an HTML email body."""
    try:
        soup = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")

        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            data = []
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if cells:
                    data.append(cells)

            if len(data) >= 2:
                # Use first row as header if it looks like a header
                df = pd.DataFrame(data[1:], columns=data[0])
                if not df.empty:
                    return df

    except Exception as e:
        logger.debug(f"HTML table extraction failed: {e}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Helper: parse date column from a DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def _find_date_column(df: pd.DataFrame) -> Optional[str]:
    """Return the name of the date column, guessing from common names."""
    date_candidates = ["date", "ngày", "ngay", "thoigian", "thời gian", "day", "dt", "period"]
    for col in df.columns:
        if any(cand in col.lower() for cand in date_candidates):
            return col
    # Try to detect a date-like column by parsing
    for col in df.columns:
        try:
            sample = df[col].dropna().head(3)
            pd.to_datetime(sample)
            return col
        except Exception:
            continue
    return None


def _parse_date_series(series: pd.Series) -> pd.Series:
    """Robustly parse dates in various Vietnamese/ISO formats."""
    def _parse_one(val):
        if pd.isna(val):
            return pd.NaT
        val = str(val).strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y%m%d"):
            try:
                return datetime.strptime(val, fmt).date()
            except Exception:
                continue
        try:
            return pd.to_datetime(val).date()
        except Exception:
            return pd.NaT

    from datetime import datetime
    return series.apply(_parse_one)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: clean numeric column
# ─────────────────────────────────────────────────────────────────────────────

def _to_numeric(series: pd.Series) -> pd.Series:
    """Strip commas/spaces and convert to float."""
    return (
        series.astype(str)
              .str.replace(",", "", regex=False)
              .str.replace(" ", "", regex=False)
              .str.replace("−", "-", regex=False)
              .pipe(pd.to_numeric, errors="coerce")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper: try reading attachment as DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def _df_from_attachment(content: bytes, filename: str) -> Optional[pd.DataFrame]:
    fn_lower = filename.lower()
    try:
        if fn_lower.endswith(".xlsx") or fn_lower.endswith(".xls"):
            return pd.read_excel(io.BytesIO(content))
        if fn_lower.endswith(".csv"):
            for enc in ("utf-8", "utf-8-sig", "latin-1"):
                try:
                    return pd.read_csv(io.BytesIO(content), encoding=enc)
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"Attachment parse failed ({filename}): {e}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Per-metric post-processing: normalise to (date, value) structure
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_metric_df(
    raw_df: pd.DataFrame, metric_key: str
) -> Optional[pd.DataFrame]:
    """
    Given a raw table extracted from an email, return a normalised DataFrame
    with at minimum a 'date' column and a value column named after `metric_key`.
    """
    if raw_df is None or raw_df.empty:
        return None

    date_col = _find_date_column(raw_df)
    if not date_col:
        logger.debug(f"[{metric_key}] No date column found. Columns: {raw_df.columns.tolist()}")
        return None

    raw_df = raw_df.copy()
    raw_df["date"] = _parse_date_series(raw_df[date_col])
    raw_df = raw_df.dropna(subset=["date"])

    # ── ZLPNewAccount: count of successfully opened accounts per day ────────
    if metric_key == "ZLPNewAccount":
        # Look for a count/total column
        val_col = None
        for col in raw_df.columns:
            if any(kw in col.lower() for kw in ["count", "số lượng", "sl", "total", "tổng", "success"]):
                val_col = col
                break
        if not val_col:
            # Sum all numeric columns except date
            numeric_cols = raw_df.select_dtypes(include="number").columns.tolist()
            if numeric_cols:
                raw_df[metric_key] = raw_df[numeric_cols].sum(axis=1)
            else:
                # Try to make numeric
                non_date = [c for c in raw_df.columns if c != "date"]
                for col in non_date:
                    raw_df[col] = _to_numeric(raw_df[col])
                raw_df[metric_key] = raw_df[[c for c in non_date if raw_df[c].notna().any()]].sum(axis=1)
        else:
            raw_df[metric_key] = _to_numeric(raw_df[val_col])

    # ── ZLPTradingTransaction: matched orders per day (ZaloPay channel) ────
    elif metric_key == "ZLPTradingTransaction":
        val_col = None
        for col in raw_df.columns:
            if any(kw in col.lower() for kw in ["zalopay", "zalo", "lệnh", "lenh", "khớp", "khop", "match"]):
                val_col = col
                break
        if not val_col:
            numeric_cols = raw_df.select_dtypes(include="number").columns.tolist()
            val_col = numeric_cols[0] if numeric_cols else None
        if val_col:
            raw_df[metric_key] = _to_numeric(raw_df[val_col])
        else:
            return None

    # ── ZLPTradingVolume: trading value (GTGD) per day via ZaloPay ─────────
    elif metric_key == "ZLPTradingVolume":
        val_col = None
        for col in raw_df.columns:
            if any(kw in col.lower() for kw in ["zalopay", "zalo", "gtgd", "giá trị", "value"]):
                val_col = col
                break
        if not val_col:
            numeric_cols = raw_df.select_dtypes(include="number").columns.tolist()
            val_col = numeric_cols[0] if numeric_cols else None
        if val_col:
            raw_df[metric_key] = _to_numeric(raw_df[val_col])
        else:
            return None

    # ── ZLPActiveUsers: active customers per month ─────────────────────────
    elif metric_key == "ZLPActiveUsers":
        val_col = None
        for col in raw_df.columns:
            if any(kw in col.lower() for kw in ["active", "kh", "user", "khách hàng"]):
                val_col = col
                break
        if not val_col:
            numeric_cols = raw_df.select_dtypes(include="number").columns.tolist()
            val_col = numeric_cols[0] if numeric_cols else None
        if val_col:
            raw_df[metric_key] = _to_numeric(raw_df[val_col])
        else:
            return None

    # ── ZLPTransactionbyusersegment: orders by GTGD segment per day ────────
    elif metric_key == "ZLPTransactionbyusersegment":
        # Keep all numeric columns; pivot later in analytics
        numeric_cols = raw_df.select_dtypes(include="number").columns.tolist()
        if not numeric_cols:
            for col in raw_df.columns:
                if col != "date":
                    raw_df[col] = _to_numeric(raw_df[col])
            numeric_cols = raw_df.select_dtypes(include="number").columns.tolist()
        raw_df[metric_key] = raw_df[numeric_cols].sum(axis=1)

    else:
        # Generic fallback
        numeric_cols = raw_df.select_dtypes(include="number").columns.tolist()
        if numeric_cols:
            raw_df[metric_key] = raw_df[numeric_cols[0]]
        else:
            return None

    result = raw_df[["date", metric_key]].dropna(subset=[metric_key])
    result = result[result[metric_key] > 0]
    return result.drop_duplicates("date").sort_values("date").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main collector
# ─────────────────────────────────────────────────────────────────────────────

def collect_zlp_data(since_days: int = 35) -> Dict[str, pd.DataFrame]:
    """
    Fetch ZLP metric emails and return a dict of metric_key → DataFrame.
    Each DataFrame has at least columns: date, <metric_key>.
    """
    client  = IMAPClient()
    results: Dict[str, pd.DataFrame] = {}

    logger.info(f"Fetching emails from {config.DNSE_SENDER_EMAIL} (last {since_days} days)")
    emails = client.get_emails_from_sender(
        sender_email=config.DNSE_SENDER_EMAIL,
        since_days=since_days,
    )

    for email in emails:
        subject    = email.get("subject", "")
        msg_id     = email.get("id", "")
        received   = email.get("receivedDateTime", "")
        metric_key = _match_subject(subject)

        if not metric_key:
            logger.debug(f"Unmatched subject: {subject!r}")
            continue

        logger.info(f"Processing [{metric_key}] ← {subject!r} ({received[:10]})")

        raw_df: Optional[pd.DataFrame] = None

        # ── Try attachments first (bundled by IMAP client — no second fetch) ─
        for att in email.get("_attachments", []):
            candidate = _df_from_attachment(att["content"], att["name"])
            if candidate is not None and not candidate.empty:
                raw_df = candidate
                logger.info(f"  Extracted from attachment: {att['name']} ({len(raw_df)} rows)")
                break

        # ── Fall back to HTML body ─────────────────────────────────────────
        if raw_df is None:
            body    = email.get("body", {}).get("content", "")
            raw_df  = _extract_table_from_html(body)
            if raw_df is not None:
                logger.info(f"  Extracted from HTML body ({len(raw_df)} rows)")

        if raw_df is None:
            logger.warning(f"  No data extracted from email: {subject!r}")
            continue

        # ── Normalise ─────────────────────────────────────────────────────
        norm_df = _normalise_metric_df(raw_df, metric_key)
        if norm_df is None or norm_df.empty:
            logger.warning(f"  Normalisation returned empty for {metric_key}")
            continue

        # Merge with any previously processed emails for the same metric
        if metric_key in results:
            combined = pd.concat([results[metric_key], norm_df])
            results[metric_key] = (
                combined.sort_values("date")
                        .drop_duplicates("date", keep="last")
                        .reset_index(drop=True)
            )
        else:
            results[metric_key] = norm_df

    logger.info(
        f"ZLP data collected: "
        + ", ".join(f"{k}({len(v)}rows)" for k, v in results.items())
    )
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = collect_zlp_data()
    for key, df in data.items():
        print(f"\n── {key} ──")
        print(df.tail(5).to_string())
