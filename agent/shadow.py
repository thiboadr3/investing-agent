"""Schaduwportefeuilles: virtueel doorgerekend met echte koersen, NIET verhandeld.

Elke schaduw start met hetzelfde bedrag als de echte paperportefeuille op de startdag,
herbalanceert naar zijn doelgewichten bij elke analyse en betaalt geschatte kosten.
Geen hefboom, geen shorts; verder geen risicoregels (bewust: om varianten te vergelijken).
"""
from __future__ import annotations

import json

from .db import DB, now

NAMES = {
    "regels_zonder_ai": "Regels zonder AI-filter (20% crypto-max)",
    "50_50": "50% crypto / 50% aandelen",
    "ai_vrij": "AI kiest volledig vrij",
    "spy": "SPY kopen en houden",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS shadows (
  name TEXT PRIMARY KEY, cash REAL, holdings TEXT, start_value REAL, start_ts TEXT,
  peak REAL, costs REAL);
CREATE TABLE IF NOT EXISTS shadow_values (ts TEXT, name TEXT, value REAL);
"""


class Shadows:
    def __init__(self, db: DB, cost_pct: dict):
        self.db = db
        self.db.conn.executescript(SCHEMA)
        self.cost = {"stock": cost_pct.get("stock", 0.05) / 100,
                     "crypto": cost_pct.get("crypto", 0.25) / 100}

    def _load(self, name):
        r = self.db.x("SELECT cash, holdings, start_value, peak, costs FROM shadows WHERE name=?",
                      (name,)).fetchone()
        return None if r is None else {"cash": r[0], "h": json.loads(r[1]), "start": r[2],
                                       "peak": r[3], "costs": r[4]}

    def _save(self, name, s):
        self.db.x("UPDATE shadows SET cash=?, holdings=?, peak=?, costs=? WHERE name=?",
                  (s["cash"], json.dumps(s["h"]), s["peak"], s["costs"], name))

    @staticmethod
    def value(s, prices: dict[str, float]) -> float:
        return s["cash"] + sum(q * prices.get(sym, 0) for sym, q in s["h"].items())

    def ensure(self, name: str, start_value: float):
        if self._load(name) is None:
            self.db.x("INSERT INTO shadows VALUES (?,?,?,?,?,?,?)",
                      (name, start_value, "{}", start_value, now(), start_value, 0.0))

    def rebalance(self, name: str, targets: dict[str, float], prices: dict[str, float],
                  min_trade: float = 100):
        """Breng de schaduw naar `targets` (gewichten). Symbolen zonder prijs blijven staan."""
        s = self._load(name)
        total = self.value(s, prices)
        syms = set(s["h"]) | set(targets)
        # eerst verkopen, dan kopen (zoals de echte agent)
        for phase in ("sell", "buy"):
            for sym in sorted(syms):
                px = prices.get(sym)
                if not px:
                    continue
                cur = s["h"].get(sym, 0) * px
                diff = targets.get(sym, 0) * total - cur
                if abs(diff) < min_trade and not (targets.get(sym, 0) == 0 and cur > 0):
                    continue
                if (phase == "sell") != (diff < 0):
                    continue
                rate = self.cost["crypto" if "/" in sym else "stock"]
                if diff < 0:
                    amt = min(-diff, cur)
                    s["h"][sym] = s["h"].get(sym, 0) - amt / px
                    s["cash"] += amt * (1 - rate)
                else:
                    amt = min(diff, s["cash"] / (1 + rate))
                    if amt < 1:
                        continue
                    s["h"][sym] = s["h"].get(sym, 0) + amt / px
                    s["cash"] -= amt * (1 + rate)
                s["costs"] += amt * rate
                if s["h"].get(sym, 0) * px < 0.01:
                    s["h"].pop(sym, None)
        self._save(name, s)

    def mark(self, prices: dict[str, float]):
        """Waardeer alle schaduwen en bewaar een meetpunt."""
        for (name,) in self.db.x("SELECT name FROM shadows").fetchall():
            s = self._load(name)
            v = self.value(s, prices)
            s["peak"] = max(s["peak"], v)
            self._save(name, s)
            self.db.x("INSERT INTO shadow_values VALUES (?,?,?)", (now(), name, round(v, 2)))

    def summary(self) -> list[dict]:
        out = []
        for name, start, costs, start_ts in self.db.x(
                "SELECT name, start_value, costs, start_ts FROM shadows").fetchall():
            vals = [v for (v,) in self.db.x(
                "SELECT value FROM shadow_values WHERE name=? ORDER BY ts", (name,)).fetchall()]
            last = vals[-1] if vals else start
            peak, mdd = start, 0.0
            for v in vals:
                peak = max(peak, v)
                mdd = max(mdd, (peak - v) / peak if peak else 0)
            out.append({"name": name, "label": NAMES.get(name, name), "start": start,
                        "value": last, "return": last / start - 1 if start else 0,
                        "max_drawdown": mdd, "costs": costs, "since": start_ts})
        return out
