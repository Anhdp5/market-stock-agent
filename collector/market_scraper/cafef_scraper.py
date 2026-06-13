"""
Market Data Scraper - CafeF / HOSE
====================================
Primary  : vnstock3 (VCI backend) -> VNINDEX OHLCV + volume
Secondary: CafeF s.cafef.vn handler -> order stats
Fallback : CafeF HTML page parsing
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
    "Accept-Language": "vi-VN,vi;q=0.9",
    "Referer": "https://cafef.vn/",
}


def fetch_vnindex_via_vnstock(start_date, end_date):
    try:
        from vnstock3 import Vnstock
        stock = Vnstock().stock("VNINDEX", source="VCI")
        df = stock.trading.history(start=start_date, end=end_date, interval="1D")
        if df is None or df.empty:
            raise ValueError("vnstock returned empty DataFrame")

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
            raise ValueError("No date column found. Columns: {}".format(df.columns.tolist()))

        df["date"] = pd.to_datetime(df["date"]).dt.date

        if "MarketVolume" not in df.columns and "volume" in df.columns:
            df["MarketVolume"] = df["volume"]

        logger.info("vnstock returned {} rows for {} -> {}".format(len(df), start_date, end_date))
        cols = ["date", "MarketVolume"]
        if "MarketValueBillion" in df.columns:
            cols.append("MarketValueBillion")
        return df[cols]

    except ImportError:
        logger.warning("vnstock3 not installed. Run: pip install vnstock3")
        return None
    except Exception as e:
        logger.warning("vnstock fetch failed: {}".format(e))
        return None


def fetch_cafef_order_stats(start_date, end_date):
    url_template = "https://s.cafef.vn/Handlers/PagingHandler.ashx/data/2/0/0/0/HOSE/{page}/"
    all_rows = []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d").date()

    for page in range(1, 6):
        try:
            url  = url_template.format(page=page)
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            rows = data.get("Data") or data.get("data") or (data if isinstance(data, list) else [])
            if not rows:
                break

            for row in rows:
                try:
                    raw_date = (
                        row.get("Ngay") or row.get("NgayGiaoDich") or
                        row.get("Date") or row.get("date") or ""
                    )
                    if not raw_date:
                        continue
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
                        "date":              row_date,
                        "MarketTransaction": int(transactions),
                        "BuyVolume":         float(buy_vol),
                        "SellVolume":        float(sell_vol),
                    })
                except Exception as e:
                    logger.debug("Row parse error: {} | row: {}".format(e, row))

            time.sleep(0.3)

        except Exception as e:
            logger.warning("CafeF order stats page {} failed: {}".format(page, e))
            break

    if all_rows:
        df = pd.DataFrame(all_rows).drop_duplicates("date").sort_values("date")
        logger.info("CafeF order stats: {} rows".format(len(df)))
        return df
    return None


def fetch_cafef_html_history(start_date, end_date):
    all_rows = []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d").date()

    url = (
        "https://cafef.vn/du-lieu/lich-su-giao-dich/hose/all-1.chn"
        "?startDate={}&endDate={}".format(start_date, end_date)
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

        rows = table.find_all("tr")[1:]
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 5:
                continue
            try:
                row_date = datetime.strptime(cells[0], "%d/%m/%Y").date()
                if not (start_dt <= row_date <= end_dt):
                    continue
                vol_str = cells[2].replace(",", "").replace(".", "")
                all_rows.append({
                    "date":         row_date,
                    "MarketVolume": float(vol_str) if vol_str else 0,
                })
            except Exception:
                continue

        if all_rows:
            df = pd.DataFrame(all_rows).drop_duplicates("date").sort_values("date")
            logger.info("CafeF HTML fallback: {} rows".format(len(df)))
            return df

    except Exception as e:
        logger.warning("CafeF HTML scrape failed: {}".format(e))

    return None


def collect_market_data(lookback_days=None, end_date=None):
    """
    Collect market data from available sources.

    Parameters
    ----------
    lookback_days : Calendar days back from end_date (default: config.LOOKBACK_DAYS)
    end_date      : Last date to collect (default: today)
    """
    if lookback_days is None:
        lookback_days = config.LOOKBACK_DAYS

    end_dt    = end_date or date.today()
    start_dt  = end_dt - timedelta(days=lookback_days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str   = end_dt.strftime("%Y-%m-%d")

    logger.info("Collecting market data {} -> {}".format(start_str, end_str))

    df_vnstock = fetch_vnindex_via_vnstock(start_str, end_str)
    df_orders  = fetch_cafef_order_stats(start_str, end_str)

    if df_vnstock is None:
        df_vnstock = fetch_cafef_html_history(start_str, end_str)

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
        logger.error("All data sources failed.")
        return pd.DataFrame(columns=[
            "date", "MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume"
        ])

    for col in ["MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume"]:
        if col not in df.columns:
            df[col] = None

    df = df[["date", "MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume"]]
    df = df.sort_values("date").reset_index(drop=True)
    logger.info("Market data collected: {} records".format(len(df)))
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = collect_market_data()
    print(df.tail(10).to_string())
