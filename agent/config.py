"""Laadt config.yaml en .env. Weigert alles behalve paper-modus."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
STOP_FILE = ROOT / "STOP"          # noodstop: bestaat dit bestand, dan geen orders
DB_PATH = Path(os.getenv("IA_DB_PATH", ROOT / "data" / "agent.db"))  # override voor tests


@dataclass(frozen=True)
class Risk:
    max_drawdown_pct: float
    max_position_pct: float
    min_cash_pct: float
    max_orders_per_day: int
    min_order_usd: float
    min_ai_confidence: float
    max_data_age_hours: float
    max_crypto_data_age_hours: float = 36
    max_crypto_total_pct: float = 20
    max_crypto_position_pct: float = 12
    pause_days: int = 28               # kalenderdagen pauze na max terugval (≈20 beursdagen)


@dataclass(frozen=True)
class Config:
    universe: tuple[str, ...]          # aandelen/ETF's
    crypto: tuple[str, ...]            # bv. ("BTC/USD", "ETH/USD")
    benchmark: str
    risk: Risk
    strategy: dict
    shadows: dict
    schedule: dict
    ai: dict
    alpaca_key: str
    alpaca_secret: str
    gemini_key: str
    sectors: dict = field(default_factory=dict)

    @property
    def all_symbols(self) -> tuple[str, ...]:
        return self.universe + self.crypto


def is_crypto(symbol: str) -> bool:
    return "/" in symbol


def load(path: Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    raw = yaml.safe_load((path or ROOT / "config.yaml").read_text())
    if raw.get("mode") != "paper":
        raise SystemExit("Alleen mode: paper is toegestaan in deze fase.")
    cr = raw.get("crypto") or {}
    risk = dict(raw["risk"])
    risk["max_crypto_total_pct"] = cr.get("max_total_pct", 20)
    risk["max_crypto_position_pct"] = cr.get("max_position_pct", 12)
    return Config(
        universe=tuple(s.upper() for s in raw["universe"]),
        crypto=tuple(s.upper() for s in cr.get("symbols", [])),
        benchmark=raw.get("benchmark", "SPY"),
        risk=Risk(**risk),
        strategy=raw.get("strategy", {}),
        shadows=raw.get("shadows", {"enabled": False}),
        schedule=raw["schedule"],
        ai=raw["ai"],
        alpaca_key=os.getenv("ALPACA_API_KEY", ""),
        alpaca_secret=os.getenv("ALPACA_SECRET_KEY", ""),
        gemini_key=os.getenv("GEMINI_API_KEY", ""),
        sectors=json.loads((ROOT / "agent" / "sectors.json").read_text())
        if (ROOT / "agent" / "sectors.json").exists() else {},
    )
