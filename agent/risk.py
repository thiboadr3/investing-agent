"""Onafhankelijke risicolaag. Pure functies, zonder AI of netwerk: makkelijk te testen.

Elke voorgestelde order passeert check_order(). Eén geschonden regel = geen order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Risk


@dataclass
class Proposal:
    symbol: str
    side: str            # "buy" | "sell"
    notional: float      # USD
    confidence: float


@dataclass
class Context:
    equity: float
    cash: float
    peak_equity: float
    position_values: dict[str, float]
    position_qty: dict[str, float]
    open_order_symbols: set[str]
    universe: set[str]
    orders_today: int
    market_open: bool
    account_ok: bool
    stop_file: bool
    price_as_of: dict[str, datetime]


def drawdown_pct(equity: float, peak: float) -> float:
    return 0.0 if peak <= 0 else (peak - equity) / peak * 100


def check_order(p: Proposal, c: Context, r: Risk, now: datetime | None = None) -> str | None:
    """Geeft None als de order mag, anders de naam van de geschonden regel."""
    now = now or datetime.now(timezone.utc)
    if c.stop_file:
        return "noodstop_actief"
    if not c.account_ok:
        return "account_status_onduidelijk"
    crypto = "/" in p.symbol
    if not crypto and not c.market_open:
        return "markt_gesloten"   # crypto handelt 24/7
    if p.symbol not in c.universe:
        return "niet_in_universum"
    if p.side not in ("buy", "sell") or p.notional <= 0:
        return "ongeldige_order"
    if p.symbol in c.open_order_symbols:
        return "open_order_bestaat_al"
    if c.orders_today >= r.max_orders_per_day:
        return "max_orders_per_dag"
    if p.notional < r.min_order_usd:
        return "order_te_klein"
    if p.confidence < r.min_ai_confidence:
        return "te_lage_zekerheid"
    as_of = c.price_as_of.get(p.symbol)
    max_age = r.max_crypto_data_age_hours if crypto else r.max_data_age_hours
    if as_of is None or (now - as_of).total_seconds() / 3600 > max_age:
        return "verouderde_data"

    if p.side == "sell":
        if c.position_qty.get(p.symbol, 0) <= 0:
            return "geen_positie_om_te_verkopen"   # geen shorts
        if p.notional > c.position_values.get(p.symbol, 0) * 1.001:
            return "verkoop_groter_dan_positie"
        return None

    # buy-regels
    if drawdown_pct(c.equity, c.peak_equity) >= r.max_drawdown_pct:
        return "max_terugval_bereikt"
    new_value = c.position_values.get(p.symbol, 0) + p.notional
    cap = r.max_crypto_position_pct if crypto else r.max_position_pct
    if new_value > c.equity * cap / 100 * 1.001:
        return "max_positiegrootte"
    if crypto:
        crypto_total = sum(v for s, v in c.position_values.items() if "/" in s) + p.notional
        if crypto_total > c.equity * r.max_crypto_total_pct / 100 * 1.001:
            return "max_crypto_aandeel"
    if c.cash - p.notional < c.equity * r.min_cash_pct / 100 * 0.999:   # afrondingsmarge
        return "cashbuffer"
    return None
