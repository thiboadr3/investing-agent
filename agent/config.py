"""Laadt config.yaml en .env. Weigert alles behalve paper-modus."""
from __future__ import annotations

import os
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Config:
    universe: tuple[str, ...]
    benchmark: str
    risk: Risk
    schedule: dict
    ai: dict
    alpaca_key: str
    alpaca_secret: str
    gemini_key: str


def load(path: Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    raw = yaml.safe_load((path or ROOT / "config.yaml").read_text())
    if raw.get("mode") != "paper":
        raise SystemExit("Alleen mode: paper is toegestaan in deze fase.")
    return Config(
        universe=tuple(s.upper() for s in raw["universe"]),
        benchmark=raw.get("benchmark", "SPY"),
        risk=Risk(**raw["risk"]),
        schedule=raw["schedule"],
        ai=raw["ai"],
        alpaca_key=os.getenv("ALPACA_API_KEY", ""),
        alpaca_secret=os.getenv("ALPACA_SECRET_KEY", ""),
        gemini_key=os.getenv("GEMINI_API_KEY", ""),
    )
