"""Vertaalt doelgewichten naar concrete ordervoorstellen (eerst verkopen, dan kopen)."""
from __future__ import annotations

from .risk import Proposal


def proposals(targets: dict[str, float], equity: float, position_values: dict[str, float],
              universe: set[str], min_order_usd: float, confidence: float = 1.0,
              allow_buys: bool = True, band: float = 0.0) -> list[Proposal]:
    """band: bestaande posities enkel bijsturen als de afwijking > band × portefeuille.
    Nieuwe posities en volledige verkopen gebeuren altijd."""
    out = []
    for sym in sorted(universe):
        current = position_values.get(sym, 0.0)
        target = targets.get(sym, 0.0) * equity
        diff = target - current
        if diff > 0 and not allow_buys:
            continue
        if diff < 0 and target <= 0 and current > 0:
            diff = -current                  # volledig sluiten
        elif abs(diff) < min_order_usd or (current > 0 and abs(diff) < band * equity):
            continue
        out.append(Proposal(sym, "buy" if diff > 0 else "sell", abs(diff), confidence))
    return sorted(out, key=lambda p: p.side != "sell")
