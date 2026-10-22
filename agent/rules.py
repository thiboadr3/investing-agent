"""Regelstrategie: trendvolging + momentum + positiegrootte op basis van volatiliteit.

Pure functies zonder netwerk of AI. Geeft doelgewichten (0..1 van de portefeuille).
"""
from __future__ import annotations

from .data import Snapshot


def _inverse_vol(cands: list[Snapshot], budget: float, cap: float) -> dict[str, float]:
    """Verdeel `budget` omgekeerd evenredig met volatiliteit, met max `cap` per positie.
    Wat door de cap niet verdeeld raakt, gaat naar de overige posities; de rest blijft cash."""
    w: dict[str, float] = {}
    left, pool = budget, [c for c in cands if c.vol_3m and c.vol_3m > 0]
    while pool and left > 1e-9:
        inv = {c.symbol: 1 / c.vol_3m for c in pool}
        tot = sum(inv.values())
        capped = []
        for c in pool:
            add = left * inv[c.symbol] / tot
            if w.get(c.symbol, 0) + add >= cap:
                capped.append(c)
        if not capped:
            for c in pool:
                w[c.symbol] = w.get(c.symbol, 0) + left * inv[c.symbol] / tot
            left = 0
            break
        for c in capped:
            left -= cap - w.get(c.symbol, 0)
            w[c.symbol] = cap
        pool = [c for c in pool if c not in capped]
    return {s: round(v, 4) for s, v in w.items() if v > 0}


def stock_targets(snaps: dict[str, Snapshot], budget: float, top_n: int,
                  cap: float) -> tuple[dict[str, float], dict[str, str]]:
    """Aandelen/ETF's: boven 200d-gemiddelde en positief 12-1 momentum; top N op momentum."""
    why: dict[str, str] = {}
    eligible = []
    for s in snaps.values():
        if s.crypto:
            continue
        if s.above_200d is not True:
            why[s.symbol] = "onder 200d-gemiddelde"
        elif s.mom_12_1 is None or s.mom_12_1 <= 0:
            why[s.symbol] = "geen positief 12-1 momentum"
        else:
            eligible.append(s)
    eligible.sort(key=lambda s: s.mom_12_1, reverse=True)
    for s in eligible[top_n:]:
        why[s.symbol] = f"momentum {s.mom_12_1:+.0%}, buiten top {top_n}"
    chosen = eligible[:top_n]
    w = _inverse_vol(chosen, budget, cap)
    for s in chosen:
        why[s.symbol] = f"trend OK, momentum {s.mom_12_1:+.0%}, vol {s.vol_3m:.0%}"
    return w, why


def crypto_targets(snaps: dict[str, Snapshot], max_total: float, cap: float,
                   ) -> tuple[dict[str, float], dict[str, str]]:
    """Crypto: enkel munten boven 200d-gemiddelde en met positief 3m-rendement.
    Hoe meer munten in een trend, hoe groter het crypto-deel (max `max_total`)."""
    why: dict[str, str] = {}
    all_c = [s for s in snaps.values() if s.crypto]
    ok = []
    for s in all_c:
        if s.above_200d is not True:
            why[s.symbol] = "onder 200d-gemiddelde → 0%"
        elif s.ret_3m is None or s.ret_3m <= 0:
            why[s.symbol] = "geen positief 3m-rendement → 0%"
        else:
            ok.append(s)
    if not all_c or not ok:
        return {}, why
    budget = max_total * len(ok) / len(all_c)
    w = _inverse_vol(ok, budget, cap)
    for s in ok:
        why[s.symbol] = f"trend OK, 3m {s.ret_3m:+.0%}, vol {s.vol_3m:.0%}"
    return w, why


def targets(snaps: dict[str, Snapshot], strat: dict, stock_cap: float,
            crypto_total: float, crypto_cap: float) -> tuple[dict[str, float], dict[str, str]]:
    invested = strat.get("target_invested_pct", 95) / 100
    cw, cwhy = crypto_targets(snaps, crypto_total, crypto_cap)
    sw, swhy = stock_targets(snaps, invested - sum(cw.values()), strat.get("stock_top_n", 10),
                             stock_cap)
    return {**sw, **cw}, {**swhy, **cwhy}


def fixed_split(snaps: dict[str, Snapshot], strat: dict, crypto_share: float,
                stock_cap: float) -> dict[str, float]:
    """Schaduw '50/50': vast crypto-deel (zonder trendfilter), rest via aandelenregels."""
    invested = strat.get("target_invested_pct", 95) / 100
    cr = [s for s in snaps.values() if s.crypto]
    cw = _inverse_vol(cr, invested * crypto_share, 1.0)
    sw, _ = stock_targets(snaps, invested * (1 - crypto_share), strat.get("stock_top_n", 10),
                          stock_cap)
    return {**sw, **cw}
