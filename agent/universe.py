"""Dynamisch universum: alle Amerikaanse aandelen die vlot verhandelbaar zijn.

Geen vaste lijst en geen beperking tot de S&P 500: ook kleinere bedrijven komen in aanmerking,
zolang ze genoeg verhandeld worden (anders kost in- en uitstappen te veel en is de koers
makkelijk te manipuleren). ETF's, fondsen, warrants, units en preferente aandelen vallen af.

Stappen (raw REST, snel genoeg voor ~6.000 tickers):
  1. Alpaca-lijst: actief, verhandelbaar, fractioneel (nodig voor orders in dollars),
     beurs NYSE/NASDAQ/AMEX, naam is geen fonds/warrant/...
  2. Voorfilter op de laatste 10 dagen (SIP-volume, alle beurzen): prijs en dollarvolume.
  3. Volledige koershistoriek (±14 maanden) voor wie overblijft -> Snapshots.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import requests

from .data import Snapshot, build_snapshot

ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
EXCHANGES = {"NYSE", "NASDAQ", "AMEX"}
NOT_STOCK = re.compile(
    r"\b(ETF|ETN|FUND|TRUST UNITS?|WARRANTS?|RIGHTS?|UNITS?|PREFERRED|PFD"
    r"|NOTES?|DEBENTURES?|ACQUISITION CORP|SPAC|ISHARES|PROSHARES|DIREXION|SPDR"
    r"|LEVERAGED|INVERSE|2X|3X|PREFERENCE|ACQUISITION|QQQ|SERIES 1|MUNICIPAL"
    r"|(INCOME|SECURITIES|UTILITY|OPPORTUNITIES|DIVIDEND|EQUITY|BOND|CREDIT|GROWTH) TRUST"
    r"|CLOSED[- ]END|INCOME FUND|PORTFOLIO)\b", re.I)


def is_common_stock(a: dict) -> bool:
    sym, name = a.get("symbol", ""), a.get("name") or ""
    if not (a.get("tradable") and a.get("fractionable") and a.get("exchange") in EXCHANGES):
        return False
    if not re.fullmatch(r"[A-Z]{1,5}(\.[AB])?", sym):   # geen warrants/units-notaties
        return False
    return not NOT_STOCK.search(name)


class Scanner:
    def __init__(self, key: str, secret: str):
        self.h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    def _get(self, url, params, tries=4):
        for i in range(tries):
            r = requests.get(url, params=params, headers=self.h, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 + 3 * i)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    def assets(self) -> dict[str, str]:
        """symbool -> bedrijfsnaam, enkel gewone aandelen."""
        data = self._get(ASSETS_URL, {"status": "active", "asset_class": "us_equity"})
        return {a["symbol"]: a["name"] for a in data if is_common_stock(a)}

    def bars(self, symbols: list[str], days: int, chunk: int = 400) -> dict[str, list[dict]]:
        """Dagkoersen (SIP = alle beurzen, gecorrigeerd voor splitsingen/dividenden)."""
        start = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        end = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        out: dict[str, list[dict]] = {}
        for i in range(0, len(symbols), chunk):
            params = {"symbols": ",".join(symbols[i:i + chunk]), "timeframe": "1Day",
                      "start": start, "end": end, "feed": "sip", "adjustment": "all",
                      "limit": 10000}
            while True:
                j = self._get(BARS_URL, params)
                for s, rows in (j.get("bars") or {}).items():
                    out.setdefault(s, []).extend(rows)
                if not j.get("next_page_token"):
                    break
                params["page_token"] = j["next_page_token"]
        return out

    def scan(self, min_price: float, min_dollar_vol: float, sma_days: int = 200,
             always: list[str] | None = None, log=print) -> tuple[dict[str, Snapshot], dict[str, str]]:
        """Geeft (snapshots, namen). `always` (bv. benchmark, bezette posities) wordt altijd
        opgehaald, ook als het niet door de filters komt."""
        t0 = time.time()
        names = self.assets()
        recent = self.bars(sorted(names), 16)
        keep = []
        for s, rows in recent.items():
            rows = rows[-10:]
            if not rows:
                continue
            dv = sorted(r["c"] * r["v"] for r in rows)[len(rows) // 2]   # mediaan
            if rows[-1]["c"] >= min_price and dv >= min_dollar_vol:
                keep.append(s)
        always = [s for s in (always or []) if "/" not in s]
        full = self.bars(sorted(set(keep) | set(always)), 420)
        snaps = {}
        for s, rows in full.items():
            if len(rows) < 30:
                continue
            closes = [float(r["c"]) for r in rows]
            as_of = datetime.fromisoformat(rows[-1]["t"].replace("Z", "+00:00"))
            snap = build_snapshot(s, closes, as_of, False, sma_days)
            tail = rows[-20:]
            snap.dollar_vol = sorted(r["c"] * r["v"] for r in tail)[len(tail) // 2]
            snap.name = names.get(s, "")
            snaps[s] = snap
        log(f"Scan: {len(names)} aandelen, {len(keep)} liquide, {len(snaps)} met historiek "
            f"({time.time() - t0:.0f}s)")
        return snaps, names
