"""Layer penyimpanan (SQLite).

Menyimpan: watchlist, snapshot data harian, sentimen/berita, trading plan
harian, posisi portofolio, dan log alert. SQLite dipilih karena bawaan
Python (tanpa dependensi tambahan) dan cukup untuk beban single-VPS.

Semua akses melalui fungsi di modul ini agar skema terpusat.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from src.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    ticker      TEXT PRIMARY KEY,
    added_at    TEXT NOT NULL,
    source      TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS daily_data (
    ticker      TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    payload     TEXT NOT NULL,          -- JSON: OHLCV, foreign flow, dll.
    PRIMARY KEY (ticker, trade_date)
);

CREATE TABLE IF NOT EXISTS sentiment (
    trade_date  TEXT PRIMARY KEY,
    payload     TEXT NOT NULL           -- JSON: sentimen agregat, katalis, dll.
);

CREATE TABLE IF NOT EXISTS trade_plan (
    trade_date  TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    payload     TEXT NOT NULL,          -- JSON: entry/tp/sl/rrr/rekomendasi
    active      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (trade_date, ticker)
);

CREATE TABLE IF NOT EXISTS portfolio (
    ticker      TEXT PRIMARY KEY,
    lots        INTEGER,
    avg_price   REAL,
    last_price  REAL,
    updated_at  TEXT NOT NULL,
    payload     TEXT                    -- JSON mentah hasil ekstraksi
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- BUY | TP | CUTLOSS | INFO
    price       REAL,
    message     TEXT
);
"""


def _connect() -> sqlite3.Connection:
    path: Path = settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(_SCHEMA)


def _today() -> str:
    return date.today().isoformat()


# --- Watchlist ---
def add_to_watchlist(ticker: str, source: str = "", note: str = "") -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist(ticker, added_at, source, note) "
            "VALUES (?,?,?,?)",
            (ticker.upper(), datetime.utcnow().isoformat(), source, note),
        )


def get_watchlist() -> list[str]:
    with db() as conn:
        rows = conn.execute("SELECT ticker FROM watchlist ORDER BY ticker").fetchall()
    return [r["ticker"] for r in rows]


def remove_from_watchlist(ticker: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM watchlist WHERE ticker=?", (ticker.upper(),))


def reset_watchlist() -> None:
    with db() as conn:
        conn.execute("DELETE FROM watchlist")


# --- Data harian ---
def save_daily_data(ticker: str, payload: dict[str, Any], trade_date: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_data(ticker, trade_date, payload) VALUES (?,?,?)",
            (ticker.upper(), trade_date or _today(), json.dumps(payload)),
        )


def get_daily_data(ticker: str, trade_date: str | None = None) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT payload FROM daily_data WHERE ticker=? AND trade_date=?",
            (ticker.upper(), trade_date or _today()),
        ).fetchone()
    return json.loads(row["payload"]) if row else None


# --- Sentimen / berita ---
def save_sentiment(payload: dict[str, Any], trade_date: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sentiment(trade_date, payload) VALUES (?,?)",
            (trade_date or _today(), json.dumps(payload)),
        )


def get_sentiment(trade_date: str | None = None) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT payload FROM sentiment WHERE trade_date=?",
            (trade_date or _today(),),
        ).fetchone()
    return json.loads(row["payload"]) if row else None


# --- Trade plan ---
def save_trade_plan(ticker: str, payload: dict[str, Any], trade_date: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO trade_plan(trade_date, ticker, payload, active) "
            "VALUES (?,?,?,1)",
            (trade_date or _today(), ticker.upper(), json.dumps(payload)),
        )


def get_active_plans(trade_date: str | None = None) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT ticker, payload FROM trade_plan WHERE trade_date=? AND active=1",
            (trade_date or _today(),),
        ).fetchall()
    out = []
    for r in rows:
        plan = json.loads(r["payload"])
        plan["ticker"] = r["ticker"]
        out.append(plan)
    return out


def deactivate_plans(trade_date: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE trade_plan SET active=0 WHERE trade_date=?",
            (trade_date or _today(),),
        )


# --- Portfolio ---
def upsert_position(
    ticker: str,
    lots: int | None,
    avg_price: float | None,
    last_price: float | None,
    payload: dict[str, Any] | None = None,
) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio(ticker, lots, avg_price, last_price, "
            "updated_at, payload) VALUES (?,?,?,?,?,?)",
            (
                ticker.upper(), lots, avg_price, last_price,
                datetime.utcnow().isoformat(),
                json.dumps(payload or {}),
            ),
        )


def get_portfolio() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM portfolio ORDER BY ticker").fetchall()
    return [dict(r) for r in rows]


def clear_portfolio() -> None:
    with db() as conn:
        conn.execute("DELETE FROM portfolio")


# --- Alerts ---
def log_alert(ticker: str, kind: str, price: float | None, message: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO alerts(created_at, ticker, kind, price, message) VALUES (?,?,?,?,?)",
            (datetime.utcnow().isoformat(), ticker.upper(), kind, price, message),
        )


def already_alerted_today(ticker: str, kind: str) -> bool:
    """Cegah spam: cek apakah alert jenis tertentu sudah dikirim hari ini."""
    start = _today() + "T00:00:00"
    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM alerts WHERE ticker=? AND kind=? AND created_at>=? LIMIT 1",
            (ticker.upper(), kind, start),
        ).fetchone()
    return row is not None
