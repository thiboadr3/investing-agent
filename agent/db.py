"""SQLite-logboek: alle beslissingen, orders, snapshots, nieuws en fouten."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  ts TEXT, equity REAL, cash REAL, peak_equity REAL, positions TEXT);
CREATE TABLE IF NOT EXISTS decisions (
  ts TEXT, cycle_id TEXT, symbol TEXT, action TEXT, target_weight REAL,
  confidence REAL, reasons_for TEXT, reasons_against TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS orders (
  ts TEXT, client_order_id TEXT UNIQUE, symbol TEXT, side TEXT,
  notional REAL, qty REAL, status TEXT, broker_id TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS rejections (
  ts TEXT, cycle_id TEXT, symbol TEXT, side TEXT, rule TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY, ts TEXT, created_at TEXT, symbols TEXT,
  headline TEXT, summary TEXT, source TEXT, url TEXT);
CREATE TABLE IF NOT EXISTS events (
  ts TEXT, level TEXT, message TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS fiches (
  symbol TEXT, day TEXT, data TEXT, PRIMARY KEY (symbol, day));
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def x(self, sql: str, params: tuple = ()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    # --- state ---
    def get(self, key: str, default=None):
        row = self.x("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value) -> None:
        self.x("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    # --- logging ---
    def event(self, level: str, message: str, detail=None) -> None:
        self.x("INSERT INTO events VALUES (?,?,?,?)",
               (now(), level, message, json.dumps(detail, default=str) if detail else None))
        print(f"[{level}] {message}")

    def order_exists(self, client_order_id: str) -> bool:
        return self.x("SELECT 1 FROM orders WHERE client_order_id=?",
                      (client_order_id,)).fetchone() is not None

    def orders_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        return self.x("SELECT COUNT(*) FROM orders WHERE ts LIKE ? AND status != 'dry_run'",
                      (today + "%",)).fetchone()[0]
