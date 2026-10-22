"""Vertaalt AI-voorstellen (doelgewichten) naar concrete ordervoorstellen."""
from __future__ import annotations

from .risk import Proposal


def proposals(decisions: list[dict], equity: float, position_values: dict[str, float],
              min_order_usd: float) -> list[Proposal]:
    out = []
    for d in decisions:
        sym, current = d["symbol"], position_values.get(d["symbol"], 0.0)
        if d["action"] == "hold":
            continue
        target = d["target_weight"] * equity
        if d["action"] == "sell":
            target = min(target, current)   # sell mag nooit verhogen
        elif d["action"] == "buy":
            target = max(target, current)   # buy mag nooit verlagen
        diff = target - current
        if abs(diff) < min_order_usd:
            continue
        out.append(Proposal(sym, "buy" if diff > 0 else "sell", abs(diff), d["confidence"]))
    # eerst verkopen (maakt cash vrij), daarna kopen
    return sorted(out, key=lambda p: p.side != "sell")
