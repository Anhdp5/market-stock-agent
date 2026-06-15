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
    date                TEXT PRIMARY KEY,  -- YYYY-MM-DD
    -- Market (HOSE aggregate) from CafeF PriceHistory
    MarketVolume        REAL,  -- matched volume (shares)
    MarketValue         REAL,  -- matched value (Billion VND)
    BuyVolume           REAL,  -- buy-side volume
    SellVolume          REAL,  -- sell-side volume
    -- Market order counts from CafeF ThongKeDL
    MarketOrderCount    REAL,
    MarketBuyOrders     REAL,
    MarketSellOrders    REAL,
    -- ZaloPay internal metrics
    ZLPNewAccount       REAL,  -- new accounts (ACTIVE statuses)
    ZLPTransaction      REAL,  -- orders (sum of GTGD segment table)
    ZLPValue            REAL,  -- GTGD trading value (Billion VND, est. from value buckets)
    ZLPActiveUsers      REAL,  -- daily active users
    ZLPActiveSellUsers  REAL,  -- daily active sell users
    ZLPActiveBuyUsers   REAL,  -- daily active buy users
    ZLPActiveUsersMonthly REAL, -- monthly active user (forward-filled)
    -- Metadata
    updated_at          TEXT DEFAULT (datetime('now'))
);
"""

# Columns to add if upgrading from old schema
_MIGRATION_COLS = {
    "MarketValue":          "REAL",
    "MarketOrderCount":     "REAL",
    "MarketBuyOrders":      "REAL",
    "MarketSellOrders":     "REAL",
    "ZLPTransaction":       "REAL",
    "ZLPValue":             "REAL",
    "ZLPActiveSellUsers":   "REAL",
    "ZLPActiveBuyUsers":    "REAL",
    "ZLPActiveUsersMonthly":"REAL",
}

UPSERT_SQL = """
INSERT INTO daily_market (
    date,
    MarketVolume, MarketValue, BuyVolume, SellVolume,
    MarketOrderCount, MarketBuyOrders, MarketSellOrders,
    ZLPNewAccount, ZLPTransaction, ZLPValue,
    ZLPActiveUsers, ZLPActiveSellUsers, ZLPActiveBuyUsers,
    ZLPActiveUsersMonthly,
    updated_at
) VALUES (
    :date,
    :MarketVolume, :MarketValue, :BuyVolume, :SellVolume,
    :MarketOrderCount, :MarketBuyOrders, :MarketSellOrders,
    :ZLPNewAccount, :ZLPTransaction, :ZLPValue,
    :ZLPActiveUsers, :ZLPActiveSellUsers, :ZLPActiveBuyUsers,
    :ZLPActiveUsersMonthly,
    datetime('now')
)
ON CONFLICT(date) DO UPDATE SET
    MarketVolume         = COALESCE(excluded.MarketVolume,        daily_market.MarketVolume),
    MarketValue          = COALESCE(excluded.MarketValue,         daily_market.MarketValue),
    BuyVolume            = COALESCE(excluded.BuyVolume,           daily_market.BuyVolume),
    SellVolume           = COALESCE(excluded.SellVolume,          daily_market.SellVolume),
    MarketOrderCount     = COALESCE(excluded.MarketOrderCount,    daily_market.MarketOrderCount),
    MarketBuyOrders      = COALESCE(excluded.MarketBuyOrders,     daily_market.MarketBuyOrders),
    MarketSellOrders     = COALESCE(excluded.MarketSellOrders,    daily_market.MarketSellOrders),
    ZLPNewAccount        = COALESCE(excluded.ZLPNewAccount,       daily_market.ZLPNewAccount),
    ZLPTransaction       = COALESCE(excluded.ZLPTransaction,      daily_market.ZLPTransaction),
    ZLPValue             = COALESCE(excluded.ZLPValue,            daily_market.ZLPValue),
    ZLPActiveUsers       = COALESCE(excluded.ZLPActiveUsers,      daily_market.ZLPActiveUsers),
    ZLPActiveSellUsers   = COALESCE(excluded.ZLPActiveSellUsers,  daily_market.ZLPActiveSellUsers),
    ZLPActiveBuyUsers    = COALESCE(excluded.ZLPActiveBuyUsers,   daily_market.ZLPActiveBuyUsers),
    ZLPActiveUsersMonthly= COALESCE(excluded.ZLPActiveUsersMonthly, daily_market.ZLPActiveUsersMonthly),
    updated_at           = datetime('now');
"""

ALL_COLUMNS = [
    "date",
    "MarketVolume", "MarketValue", "BuyVolume", "SellVolume",
    "MarketOrderCount", "MarketBuyOrders", "MarketSellOrders",
    "ZLPNewAccount", "ZLPTransaction", "ZLPValue",
    "ZLPActiveUsers", "ZLPActiveSellUsers", "ZLPActiveBuyUsers",
    "ZLPActiveUsersMonthly",
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
            # Migrate: add any missing columns to existing DBs
            existing = {row[1] for row in conn.execute("PRAGMA table_info(daily_market)")}
            for col, dtype in _MIGRATION_COLS.items():
                if col not in existing:
                    conn.execute(f"ALTER TABLE daily_market ADD COLUMN {col} {dtype}")
                    logger.info(f"Migrated DB: added column {col}")
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

    def _safe_cols(self) -> str:
        """Return SELECT clause using only columns that exist in the DB."""
        with self._conn() as conn:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(daily_market)")}
        cols = [c for c in ALL_COLUMNS if c in existing]
        return ", ".join(cols)

    def read_last_n_trading_days(self, n: int = 7) -> pd.DataFrame:
        cols = self._safe_cols()
        sql = f"""
            SELECT {cols}
            FROM daily_market
            WHERE MarketVolume IS NOT NULL
               OR ZLPTransaction IS NOT NULL
            ORDER BY date DESC
            LIMIT {n}
        """
        with self._conn() as conn:
            df = pd.read_sql_query(sql, conn, parse_dates=["date"])
        return df.sort_values("date").reset_index(drop=True)

    def read_range(self, start: str, end: str) -> pd.DataFrame:
        cols = self._safe_cols()
        sql = f"""
            SELECT {cols}
            FROM daily_market
            WHERE date >= '{start}' AND date <= '{end}'
            ORDER BY date
        """
        with self._conn() as conn:
            df = pd.read_sql_query(sql, conn, parse_dates=["date"])
        return df.reset_index(drop=True)

    def read_all(self) -> pd.DataFrame:
        cols = self._safe_cols()
        sql = f"SELECT {cols} FROM daily_market ORDER BY date"
        with self._conn() as conn:
            df = pd.read_sql_query(sql, conn, parse_dates=["date"])
        return df.reset_index(drop=True)

    def latest_date(self) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(date) AS d FROM daily_market"
            ).fetchone()
        return row["d"] if row else None
