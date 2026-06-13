"""
Market Data Scraper - CafeF / HOSE
====================================
Collects daily market-wide trading stats for the Vietnamese stock exchange.

Primary source  : vnstock3 (VCI/TCBS backend) → VNINDEX OHLCV + volume
Secondary source: CafeF s.cafef.vn handler    → order stats (buy/sell volumes)
Fallback        : CafeF HTML page parsing
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import logging
import time
from datetime import datetime, timedelta, date
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
    "Referer": "https://cafef.vn/",
}


# ─────────────────────────────────────────────────────────────────────────────
# PRIMARY: vnstock3
# ─────────────────────────────────────────────────────────────────────────────

def fetch_vnindex_via_vnstock(start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """
    Use vnstock3 to download VNINDEX daily candles.
    Returns DataFrame with columns: date, close, volume (total market value in B VND).
    """
    try:
        from vnstock3 import Vnstock               # noqa: import inside function to avoid hard dep at import time
        stock = Vnstock().stock("VNINDEX", source="VCI")
        df = stock.trading.history(start=start_date, end=end_date, interval="1D")
        if df is None or df.empty:
            raise ValueError("vnstock returned empty DataFrame")

        # Normalise column names (vnstock may vary between versions)
        df.columns = [c.lower() for c in df.columns]
        rename = {}
        for col in df.columns:
            if col in ("time", "datetime", "tradingdate"):
                rename[col] = "date"
            if col in ("volume", "matchedvolume", "totalvolume"):
                rename[col] = "MarketVolume"
            if col in ("value", "totalvalue", "tradingvalue"):
                rename[col] = "MarketValueBillion"

        df = df.rename(columns=rename)

        if "date" not in df.columns:
            raise ValueError(f"No date column in vnstock result. Columns: {df.columns.tolist()}")

        df["date"] = pd.to_datetime(df["date"]).dt.date

        # volume from vnstock for VNINDEX = total market matched volume (shares)
        # value = total trading value in billion VND
        if "MarketVolume" not in df.columns and "volume" in df.columns:
            df["MarketVolume"] = df["volume"]

        logger.info(f"vnstock returned {len(df)} rows for {start_date}→{end_date}")
        return df[["date", "MarketVolume"] + (["MarketValueBillion"] if "MarketValueBillion" in df.columns else [])]

    except ImportError:
        logger.warning("vnstock3 not installed. Run: pip install vnstock3 --break-system-packages")
        return None
    except Exception as e:
        logger.warning(f"vnstock fetch failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SECONDARY: CafeF s.cafef.vn JSON handler
# ─────────────────────────────────────────────────────────────────────────────

def fetch_cafef_order_stats(start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """
    Fetch market-wide order statistics from CafeF's internal handler.
    Endpoint: https://s.cafef.vn/Handlers/PagingHandler.ashx/data/2/0/0/0/HOSE/{page}/
    Returns DataFrame with: date, MarketTransaction, BuyVolume, SellVolume
    """
    url_template = (
        "https://s.cafef.vn/Handlers/PagingHandler.ashx/data/2/0/0/0/HOSE/{page}/"
    )
    all_rows = []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d").date()

    for page in range(1, 6):   # up to 5 pages × ~10 rows = 50 days of data
        try:
            url = url_template.format(page=page)
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            # CafeF returns {"Data": [...], "TotalCount": N}
            rows = data.get("Data") or data.get("data") or (data if isinstance(data, list) else [])
            if not rows:
                break

            for row in rows:
                try:
                    # Key names vary – handle multiple naming conventions
                    raw_date = (
                        row.get("Ngay") or row.get("NgayGiaoDich") or
                        row.get("Date") or row.get("date") or ""
                    )
                    if not raw_date:
                        continue
                    # Parse Vietnamese date format: "14/04/2026" or ISO
                    if "/" in str(raw_date):
                        row_date = datetime.strptime(raw_date.strip(), "%d/%m/%Y").date()
                    else:
                        row_date = datetime.fromisoformat(str(raw_date)[:10]).date()

                    if not (start_dt <= row_date <= end_dt):
                        continue

                    transactions = (
                        row.get("SoLenhKhop") or row.get("TotalMatch") or
                        row.get("tongLenhKhop") or row.get("Solenh") or 0
                    )
                    buy_vol = (
                        row.get("KLDatMua") or row.get("BuyVolume") or
                        row.get("kldatmua") or row.get("TongKLMua") or 0
                    )
                    sell_vol = (
                        row.get("KLDatBan") or row.get("SellVolume") or
                        row.get("kldatban") or row.get("TongKLBan") or 0
                    )

                    all_rows.append({
                        "date":               row_date,
                        "MarketTransaction":  int(transactions),
                        "BuyVolume":          float(buy_vol),
                        "SellVolume":         float(sell_vol),
                    })
                except Exception as parse_err:
                    logger.debug(f"Row parse error: {parse_err} | row: {row}")

            time.sleep(0.3)

        except Exception as e:
            logger.warning(f"CafeF order stats page {page} failed: {e}")
            break

    if all_rows:
        df = pd.DataFrame(all_rows).drop_duplicates("date").sort_values("date")
        logger.info(f"CafeF order stats: {len(df)} rows")
        return df
    return None


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK: CafeF HTML scraper for historical market data
# ─────────────────────────────────────────────────────────────────────────────

def fetch_cafef_html_history(start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """
    Scrape market history table from CafeF's historical data page.
    URL: https://cafef.vn/du-lieu/lich-su-giao-dich/hose/all-1.chn
    """
    all_rows = []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d").date()

    # Build date-filtered URL
    url = (
        f"https://cafef.vn/du-lieu/lich-su-giao-dich/hose/all-1.chn"
        f"?startDate={start_date}&endDate={end_date}"
    )

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        table = soup.find("table", {"id": "ctl00_ContentPlaceHolder1_ctl03_UpdatePanel1"})
        if not table:
            table = soup.find("table", class_=lambda c: c and "tablesorter" in c)
        if not table:
            logger.warning("CafeF HTML: target table not found")
            return None

        rows = table.find_all("tr")[1:]   # skip header
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 5:
                continue
            try:
                row_date = datetime.strptime(cells[0], "%d/%m/%Y").date()
                if not (start_dt <= row_date <= end_dt):
                    continue
                # Typical columns: Date | Close | Volume (matched) | Value | Open | High | Low
                vol_str = cells[2].replace(",", "").replace(".", "")
                all_rows.append({
                    "date":          row_date,
                    "MarketVolume":  float(vol_str) if vol_str else 0,
                })
            except Exception:
                continue

        if all_rows:
            df = pd.DataFrame(all_rows).drop_duplicates("date").sort_values("date")
            logger.info(f"CafeF HTML fallback: {len(df)} rows")
            return df

    except Exception as e:
        logger.warning(f"CafeF HTML scrape failed: {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN collector function
# ─────────────────────────────────────────────────────────────────────────────

def collect_market_data(
    lookback_days: int = config.LOOKBACK_DAYS
) -> pd.DataFrame:
    """
    Collect and merge market data from available sources.
    Returns a unified DataFrame with schema:
        date | MarketTransaction | MarketVolume | BuyVolume | SellVolume
    """
    end_dt   = date.today()
    start_dt = end_dt - timedelta(days=lookback_days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str   = end_dt.strftime("%Y-%m-%d")

    logger.info(f"Collecting market data {start_str} → {end_str}")

    # ── 1. Get VNINDEX volume via vnstock ──────────────────────────────────
    df_vnstock = fetch_vnindex_via_vnstock(start_str, end_str)

    # ── 2. Get order stats (transactions, buy/sell) via CafeF handler ──────
    df_orders = fetch_cafef_order_stats(start_str, end_str)

    # ── 3. Fallback: HTML scraper for volume if vnstock failed ─────────────
    if df_vnstock is None:
        df_vnstock = fetch_cafef_html_history(start_str, end_str)

    # ── Merge results ──────────────────────────────────────────────────────
    if df_vnstock is not None and df_orders is not None:
        df = df_vnstock.merge(df_orders, on="date", how="outer")
    elif df_vnstock is not None:
        df = df_vnstock.copy()
        df["MarketTransaction"] = None
        df["BuyVolume"]         = None
        df["SellVolume"]        = None
    elif df_orders is not None:
        df = df_orders.copy()
        df["MarketVolume"] = None
    else:
        logger.error("All data sources failed. Returning empty DataFrame.")
        return pd.DataFrame(columns=[
            "date", "MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume"
        ])

    # Ensure all required columns exist
    for col in ["MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume"]:
        if col not in df.columns:
            df[col] = None

    df = df[["date", "MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume"]]
    df = df.sort_values("date").reset_index(drop=True)

    logger.info(f"Market data collected: {len(df)} records")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = collect_market_data()
    print(df.tail(10).to_string())
