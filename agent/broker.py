"""Alpaca-adapter. Hardgecodeerd op de paperomgeving."""
from __future__ import annotations

from dataclasses import dataclass

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

PAPER_URL_FRAGMENT = "paper-api.alpaca.markets"


def norm_symbol(sym: str, asset_class: str = "") -> str:
    """Alpaca toont crypto-posities als 'BTCUSD'; intern gebruiken we 'BTC/USD'."""
    if "/" in sym:
        return sym
    if "crypto" in str(asset_class).lower() and sym.endswith("USD"):
        return sym[:-3] + "/USD"
    return sym


@dataclass
class Position:
    symbol: str
    qty: float
    market_value: float
    avg_entry_price: float = 0.0
    unrealized_pl: float = 0.0
    unrealized_plpc: float = 0.0


@dataclass
class Account:
    equity: float
    cash: float
    trading_blocked: bool
    status: str
    last_equity: float = 0.0   # waarde bij vorige slot


class Broker:
    def __init__(self, key: str, secret: str):
        if not key or not secret:
            raise SystemExit("Alpaca paper-keys ontbreken in .env")
        self.client = TradingClient(key, secret, paper=True)
        base = getattr(self.client, "_base_url", "")
        base = str(getattr(base, "value", base))
        if PAPER_URL_FRAGMENT not in base:
            raise SystemExit(f"Weiger te starten: geen paper-endpoint ({base}).")

    def account(self) -> Account:
        a = self.client.get_account()
        return Account(float(a.equity), float(a.cash),
                       bool(a.trading_blocked or a.account_blocked), str(a.status),
                       float(getattr(a, "last_equity", 0) or 0))

    def positions(self) -> dict[str, Position]:
        out = {}
        for p in self.client.get_all_positions():
            s = norm_symbol(p.symbol, getattr(p, "asset_class", ""))
            out[s] = Position(s, float(p.qty), float(p.market_value),
                              float(p.avg_entry_price or 0), float(p.unrealized_pl or 0),
                              float(p.unrealized_plpc or 0))
        return out

    def open_order_symbols(self) -> set[str]:
        orders = self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        return {norm_symbol(o.symbol, getattr(o, "asset_class", "")) for o in orders}

    def asset_name(self, symbol: str) -> str:
        try:
            return str(self.client.get_asset(symbol).name or symbol)
        except Exception:
            return symbol

    def market_clock(self):
        return self.client.get_clock()  # .is_open, .next_open, .next_close, .timestamp

    def submit(self, symbol: str, side: str, client_order_id: str,
               notional: float | None = None, qty: float | None = None):
        req = MarketOrderRequest(
            symbol=symbol,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            # crypto aanvaardt geen DAY-orders
            time_in_force=TimeInForce.GTC if "/" in symbol else TimeInForce.DAY,
            client_order_id=client_order_id,
            **({"notional": round(notional, 2)} if notional else {"qty": qty}),
        )
        return self.client.submit_order(req)

    def order_by_client_id(self, client_order_id: str):
        try:
            return self.client.get_order_by_client_id(client_order_id)
        except Exception:
            return None
