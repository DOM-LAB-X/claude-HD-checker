import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    internet_number TEXT UNIQUE NOT NULL,
    store_sku TEXT,
    model_number TEXT,
    name TEXT,
    brand TEXT,
    url TEXT,
    keywords_matched TEXT,
    added_at DATETIME NOT NULL,
    active BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id TEXT NOT NULL,
    checked_at DATETIME NOT NULL,
    online_price_cents INTEGER,
    clearance_price_cents INTEGER,
    savings_pct REAL,
    result_state TEXT NOT NULL,
    store_verified BOOLEAN NOT NULL,
    parser_version TEXT NOT NULL,
    error_detail TEXT
);

CREATE TABLE IF NOT EXISTS change_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id TEXT,
    event_type TEXT NOT NULL,
    detected_at DATETIME NOT NULL,
    old_clearance_price_cents INTEGER,
    new_clearance_price_cents INTEGER,
    online_price_cents INTEGER,
    savings_pct REAL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    products_attempted INTEGER NOT NULL DEFAULT 0,
    products_succeeded INTEGER NOT NULL DEFAULT 0,
    stores_with_errors TEXT,
    rate_limited BOOLEAN NOT NULL DEFAULT 0
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_product(
    conn: sqlite3.Connection,
    internet_number: str,
    store_sku: Optional[str],
    model_number: Optional[str],
    name: Optional[str],
    brand: Optional[str],
    url: str,
) -> int:
    cur = conn.execute(
        "SELECT id FROM products WHERE internet_number = ?", (internet_number,)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        """
        INSERT INTO products
            (internet_number, store_sku, model_number, name, brand, url, added_at, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (internet_number, store_sku, model_number, name, brand, url, now_utc()),
    )
    conn.commit()
    return cur.lastrowid


def last_clearance_observations(
    conn: sqlite3.Connection, product_id: int, store_id: str, limit: int = 2
):
    """Most recent `clearance_price_found` observations for product+store, newest first."""
    cur = conn.execute(
        """
        SELECT checked_at, online_price_cents, clearance_price_cents, savings_pct
        FROM price_observations
        WHERE product_id = ? AND store_id = ? AND result_state = 'clearance_price_found'
        ORDER BY checked_at DESC
        LIMIT ?
        """,
        (product_id, store_id, limit),
    )
    return cur.fetchall()


def last_observation_before(conn: sqlite3.Connection, product_id: int, store_id: str, before_checked_at: str):
    """The observation immediately preceding `before_checked_at` for product+store, any state."""
    cur = conn.execute(
        """
        SELECT result_state FROM price_observations
        WHERE product_id = ? AND store_id = ? AND checked_at < ?
        ORDER BY checked_at DESC
        LIMIT 1
        """,
        (product_id, store_id, before_checked_at),
    )
    return cur.fetchone()


def latest_clearance_per_store(conn: sqlite3.Connection, product_id: int):
    """Latest clearance_price_found observation for each store, for inter-store comparison."""
    cur = conn.execute(
        """
        SELECT store_id, clearance_price_cents, MAX(checked_at)
        FROM price_observations
        WHERE product_id = ? AND result_state = 'clearance_price_found'
        GROUP BY store_id
        """,
        (product_id,),
    )
    return cur.fetchall()


def insert_change_event(
    conn: sqlite3.Connection,
    product_id: int,
    store_id: Optional[str],
    event_type: str,
    old_clearance_price_cents: Optional[int],
    new_clearance_price_cents: Optional[int],
    online_price_cents: Optional[int],
    savings_pct: Optional[float],
    details: str,
) -> None:
    conn.execute(
        """
        INSERT INTO change_events
            (product_id, store_id, event_type, detected_at, old_clearance_price_cents,
             new_clearance_price_cents, online_price_cents, savings_pct, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id, store_id, event_type, now_utc(), old_clearance_price_cents,
            new_clearance_price_cents, online_price_cents, savings_pct, details,
        ),
    )
    conn.commit()


def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO runs (started_at, products_attempted, products_succeeded, rate_limited) VALUES (?, 0, 0, 0)",
        (now_utc(),),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    products_attempted: int,
    products_succeeded: int,
    stores_with_errors: list,
    rate_limited: bool,
) -> None:
    conn.execute(
        """
        UPDATE runs
        SET finished_at = ?, products_attempted = ?, products_succeeded = ?,
            stores_with_errors = ?, rate_limited = ?
        WHERE id = ?
        """,
        (now_utc(), products_attempted, products_succeeded, json.dumps(stores_with_errors), rate_limited, run_id),
    )
    conn.commit()


def get_product(conn: sqlite3.Connection, product_id: int):
    cur = conn.execute(
        "SELECT internet_number, name, url FROM products WHERE id = ?", (product_id,)
    )
    return cur.fetchone()


def update_product_metadata(
    conn: sqlite3.Connection,
    product_id: int,
    store_sku: Optional[str],
    model_number: Optional[str],
    name: Optional[str],
    brand: Optional[str],
) -> None:
    conn.execute(
        """
        UPDATE products
        SET store_sku = COALESCE(?, store_sku),
            model_number = COALESCE(?, model_number),
            name = COALESCE(?, name),
            brand = COALESCE(?, brand)
        WHERE id = ?
        """,
        (store_sku, model_number, name, brand, product_id),
    )
    conn.commit()


def insert_observation(
    conn: sqlite3.Connection,
    product_id: int,
    store_id: str,
    online_price_cents: Optional[int],
    clearance_price_cents: Optional[int],
    savings_pct: Optional[float],
    result_state: str,
    store_verified: bool,
    parser_version: str,
    error_detail: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO price_observations
            (product_id, store_id, checked_at, online_price_cents, clearance_price_cents,
             savings_pct, result_state, store_verified, parser_version, error_detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            store_id,
            now_utc(),
            online_price_cents,
            clearance_price_cents,
            savings_pct,
            result_state,
            store_verified,
            parser_version,
            error_detail,
        ),
    )
    conn.commit()
