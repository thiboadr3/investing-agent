"""Koersdata (Alpaca IEX, gratis) en nieuws (Alpaca News API)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
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
    vol_3m: float | None   # geannualiseerde volatiliteit


def _ret(closes: list[float], n: int) -> float | None:
    return closes[-1] / closes[-n - 1] - 1 if len(closes) > n else None


class MarketData:
    def __init__(self, key: str, secret: str):
        self.key, self.secret = key, secret
        self.client = StockHistoricalDataClient(key, secret)

    def snapshots(self, symbols: list[str]) -> dict[str, Snapshot]:
        req = StockBarsRequest(
            symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
            start=datetime.now(timezone.utc) - timedelta(days=400), feed=DataFeed.IEX)
        bars = self.client.get_stock_bars(req).data
        out = {}
        for sym, rows in bars.items():
            if not rows:
                continue
            closes = [float(b.close) for b in rows]
            daily = [closes[i] / closes[i - 1] - 1 for i in range(max(1, len(closes) - 63), len(closes))]
            vol = (sum(r * r for r in daily) / len(daily)) ** 0.5 * 252 ** 0.5 if daily else None
            sma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
            out[sym] = Snapshot(
                symbol=sym, price=closes[-1], as_of=rows[-1].timestamp,
                ret_1m=_ret(closes, 21), ret_3m=_ret(closes, 63), ret_12m=_ret(closes, 252),
                above_200d=(closes[-1] > sma200) if sma200 else None, vol_3m=vol)
        return out

    def news(self, symbols: list[str], lookback_hours: int, limit: int = 50) -> list[dict]:
        start = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
        r = requests.get(NEWS_URL, timeout=30, params={
            "symbols": ",".join(symbols), "start": start, "limit": limit, "sort": "desc"},
            headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret})
        r.raise_for_status()
        return r.json().get("news", [])
