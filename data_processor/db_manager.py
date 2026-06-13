"""
SQLite Database Manager
========================
Creates and maintains the unified daily market intelligence table.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

import config

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS daily_market (
    date                         TEXT PRIMARY KEY,   -- YYYY-MM-DD
    -- Market (HOSE aggregate)
    MarketTransaction            REAL,   -- total matched orders
    MarketVolume                 REAL,   -- total matched volume (shares)
    BuyVolume                    REAL,   -- total buy-side volume
    SellVolume                   REAL,   -- total sell-side volume
    -- ZaloPay internal
    ZLPNewAccount                REAL,   -- new accounts opened (success)
    ZLPTradingTransaction        REAL,   -- matched orders via ZaloPay
    ZLPTradingVolume             REAL,   -- trading value via ZaloPay (VND)
    ZLPActiveUsers               REAL,   -- active users (may be monthly)
    ZLPTransactionbyusersegment  REAL,   -- total orders by segment (sum)
    -- Metadata
    updated_at                   TEXT DEFAULT (datetime('now'))
);
"""

UPSERT_SQL = """
INSERT INTO daily_market (
    date,
    MarketTransaction, MarketVolume, BuyVolume, SellVolume,
    ZLPNewAccount, ZLPTradingTransaction, ZLPTradingVolume,
    ZLPActiveUsers, ZLPTransactionbyusersegment,
    updated_at
) VALUES (
    :date,
    :MarketTransaction, :MarketVolume, :BuyVolume, :SellVolume,
    :ZLPNewAccount, :ZLPTradingTransaction, :ZLPTradingVolume,
    :ZLPActiveUsers, :ZLPTransactionbyusersegment,
    datetime('now')
)
ON CONFLICT(date) DO UPDATE SET
    MarketTransaction           = COALESCE(excluded.MarketTransaction, daily_market.MarketTransaction),
    MarketVolume                = COALESCE(excluded.MarketVolume, daily_market.MarketVolume),
    BuyVolume                   = COALESCE(excluded.BuyVolume, daily_market.BuyVolume),
    SellVolume                  = COALESCE(excluded.SellVolume, daily_market.SellVolume),
    ZLPNewAccount               = COALESCE(excluded.ZLPNewAccount, daily_market.ZLPNewAccount),
    ZLPTradingTransaction       = COALESCE(excluded.ZLPTradingTransaction, daily_market.ZLPTradingTransaction),
    ZLPTradingVolume            = COALESCE(excluded.ZLPTradingVolume, daily_market.ZLPTradingVolume),
    ZLPActiveUsers              = COALESCE(excluded.ZLPActiveUsers, daily_market.ZLPActiveUsers),
    ZLPTransactionbyusersegment = COALESCE(excluded.ZLPTransactionbyusersegment, daily_market.ZLPTransactionbyusersegment),
    updated_at                  = datetime('now');
"""

ALL_COLUMNS = [
    "date",
    "MarketTransaction", "MarketVolume", "BuyVolume", "SellVolume",
    "ZLPNewAccount", "ZLPTradingTransaction", "ZLPTradingVolume",
    "ZLPActiveUsers", "ZLPTransactionbyusersegment",
]


class DBManager:

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute(DDL)
        logger.info(f"Database ready at {self.db_path}")

    # ── Write ──────────────────────────────────────────────────────────────

    def upsert_rows(self, df: pd.DataFrame):
        """Upsert a DataFrame into daily_market. Missing columns default to None."""
        if df is None or df.empty:
            return

        # Ensure all required columns exist (fill missing with None)
        for col in ALL_COLUMNS:
            if col not in df.columns:
                df[col] = None

        # Normalise date to string
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        records = df[ALL_COLUMNS].to_dict(orient="records")

        with self._conn() as conn:
            conn.executemany(UPSERT_SQL, records)
        logger.info(f"Upserted {len(records)} rows into daily_market")

    # ── Read ───────────────────────────────────────────────────────────────

    def read_last_n_trading_days(self, n: int = 7) -> pd.DataFrame:
        """
        Return the last `n` rows that have at least one non-null value column,
        ordered by date descending.
        """
        sql = f"""
            SELECT {', '.join(ALL_COLUMNS)}
            FROM daily_market
            WHERE MarketVolume IS NOT NULL
               OR ZLPTradingTransaction IS NOT NULL
               OR ZLPTradingVolume IS NOT NULL
            ORDER BY date DESC
            LIMIT {n}
        """
        with self._conn() as conn:
            df = pd.read_sql_query(sql, conn, parse_dates=["date"])
        return df.sort_values("date").reset_index(drop=True)

    def read_range(self, start: str, end: str) -> pd.DataFrame:
        """Read all rows between two ISO dates (inclusive)."""
        sql = f"""
            SELECT {', '.join(ALL_COLUMNS)}
            FROM daily_market
            WHERE date >= '{start}' AND date <= '{end}'
            ORDER BY date
        """
        with self._conn() as conn:
            df = pd.read_sql_query(sql, conn, parse_dates=["date"])
        return df.reset_index(drop=True)

    def read_all(self) -> pd.DataFrame:
        sql = f"SELECT {', '.join(ALL_COLUMNS)} FROM daily_market ORDER BY date"
        with self._conn() as conn:
            df = pd.read_sql_query(sql, conn, parse_dates=["date"])
        return df.reset_index(drop=True)

    def latest_date(self) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(date) AS d FROM daily_market"
            ).fetchone()
        return row["d"] if row else None
