"""Koersdata (Alpaca: IEX voor aandelen, gratis; crypto) en nieuws (Alpaca News API)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from alpaca.data.enums import DataFeed
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


@dataclass
class Snapshot:
    symbol: str
    price: float
    as_of: datetime
    ret_1m: float | None
    ret_3m: float | None
    ret_12m: float | None
    above_200d: bool | None
    vol_3m: float | None        # geannualiseerde volatiliteit
    mom_12_1: float | None = None  # 12 maanden rendement zonder laatste maand
    crypto: bool = False


def _ret(closes: list[float], n: int, skip: int = 0) -> float | None:
    if len(closes) <= n:
        return None
    return closes[-1 - skip] / closes[-n - 1] - 1


def build_snapshot(sym: str, closes: list[float], as_of: datetime, crypto: bool,
                   sma_days: int = 200) -> Snapshot:
    """Pure functie (testbaar): kerncijfers uit dagelijkse slotkoersen."""
    d_m, d_q, d_y = (30, 90, 365) if crypto else (21, 63, 252)
    ann = 365 if crypto else 252
    daily = [closes[i] / closes[i - 1] - 1 for i in range(max(1, len(closes) - d_q), len(closes))]
    vol = (sum(r * r for r in daily) / len(daily)) ** 0.5 * ann ** 0.5 if daily else None
    sma = sum(closes[-sma_days:]) / sma_days if len(closes) >= sma_days else None
    return Snapshot(
        symbol=sym, price=closes[-1], as_of=as_of,
        ret_1m=_ret(closes, d_m), ret_3m=_ret(closes, d_q), ret_12m=_ret(closes, d_y),
        above_200d=(closes[-1] > sma) if sma else None, vol_3m=vol,
        mom_12_1=_ret(closes, d_y, skip=d_m), crypto=crypto)


def news_symbol(sym: str) -> str:
    return sym.replace("/", "")   # BTC/USD -> BTCUSD (notatie van de nieuws-API)


class MarketData:
    def __init__(self, key: str, secret: str):
        self.key, self.secret = key, secret
        self.client = StockHistoricalDataClient(key, secret)
        self.crypto_client = CryptoHistoricalDataClient(key, secret)

    def snapshots(self, symbols: list[str], crypto_symbols: list[str] | None = None,
                  sma_days: int = 200) -> dict[str, Snapshot]:
        out = {}
        if symbols:
            req = StockBarsRequest(
                symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
                start=datetime.now(timezone.utc) - timedelta(days=420), feed=DataFeed.IEX)
            for sym, rows in self.client.get_stock_bars(req).data.items():
                if rows:
                    out[sym] = build_snapshot(sym, [float(b.close) for b in rows],
                                              rows[-1].timestamp, False, sma_days)
        if crypto_symbols:
            req = CryptoBarsRequest(
                symbol_or_symbols=crypto_symbols, timeframe=TimeFrame.Day,
                start=datetime.now(timezone.utc) - timedelta(days=420))
            for sym, rows in self.crypto_client.get_crypto_bars(req).data.items():
                if rows:
                    out[sym] = build_snapshot(sym, [float(b.close) for b in rows],
                                              rows[-1].timestamp, True, sma_days)
        return out

    def news(self, symbols: list[str], lookback_hours: int, limit: int = 50) -> list[dict]:
        if not symbols:
            return []
        start = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
        r = requests.get(NEWS_URL, timeout=30, params={
            "symbols": ",".join(news_symbol(s) for s in symbols), "start": start,
            "limit": limit, "sort": "desc"},
            headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret})
        r.raise_for_status()
        return r.json().get("news", [])
