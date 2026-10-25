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


SCORES = {"mom12": ("mom_12_1", "12-1"), "mom6": ("mom_6_1", "6-1")}


def score(s: Snapshot, key: str = "mom12") -> float | None:
    return getattr(s, SCORES[key][0])


def stock_targets(snaps: dict[str, Snapshot], budget: float, top_n: int,
                  cap: float, held: set[str] | None = None,
                  buffer: int = 0, sectors: dict[str, str] | None = None,
                  sector_cap: float | None = None, score_key: str = "mom12",
                  exclude: set[str] | None = None, max_vol: float | None = None,
                  ) -> tuple[dict[str, float], dict[str, str]]:
    """Aandelen/ETF's: boven 200d-gemiddelde en positief 12-1 momentum; top N op momentum.

    Buffer: een positie die je al bezit, blijft zolang ze in de top (N + buffer) staat.
    Dat voorkomt dat aandelen rond plaats N elke dag gekocht en weer verkocht worden.
    Sectorlimiet: max `sector_cap` van de portefeuille per sector (onbekende sector = eigen
    sector); bij selectie max floor(sector_cap / cap) namen per sector."""
    why: dict[str, str] = {}
    eligible = []
    lbl = SCORES[score_key][1]
    sc = lambda s: score(s, score_key)
    for s in snaps.values():
        if s.crypto or s.symbol in (exclude or ()):
            continue
        if s.above_200d is not True:
            why[s.symbol] = "onder 200d-gemiddelde"
        elif sc(s) is None or sc(s) <= 0:
            why[s.symbol] = f"geen positief {lbl} momentum"
        elif max_vol and (s.vol_3m or 0) > max_vol:
            why[s.symbol] = f"te beweeglijk (vol {s.vol_3m:.0%})"
        else:
            eligible.append(s)
    eligible.sort(key=sc, reverse=True)
    held = held or set()
    sectors = sectors or {}
    sec = lambda s: sectors.get(s.symbol, s.symbol)
    max_names = max(1, int(sector_cap / cap + 1e-9)) if sector_cap else top_n
    count: dict[str, int] = {}
    chosen: list[Snapshot] = []

    def take(s):
        if len(chosen) < top_n and count.get(sec(s), 0) < max_names and s not in chosen:
            chosen.append(s)
            count[sec(s)] = count.get(sec(s), 0) + 1
            return True
        return False

    for s in eligible[:top_n + buffer]:      # eerst bestaande posities binnen de buffer
        if s.symbol in held:
            take(s)
    for s in eligible:                        # dan de sterkste nieuwe
        if not take(s) and s not in chosen and len(chosen) < top_n:
            why[s.symbol] = f"momentum {sc(s):+.0%}, sectorlimiet {sec(s)}"
    chosen.sort(key=sc, reverse=True)
    for s in eligible:
        if s not in chosen and s.symbol not in why:
            why[s.symbol] = f"momentum {lbl} {sc(s):+.0%}, buiten top {top_n}"
    w = _inverse_vol(chosen, budget, cap)
    if sector_cap:                            # overgewicht per sector afschalen (rest = cash)
        tot: dict[str, float] = {}
        for s in chosen:
            tot[sec(s)] = tot.get(sec(s), 0) + w.get(s.symbol, 0)
        for s in chosen:
            if tot[sec(s)] > sector_cap and s.symbol in w:
                w[s.symbol] = round(w[s.symbol] * sector_cap / tot[sec(s)], 4)
    for s in chosen:
        why[s.symbol] = f"trend OK, momentum {lbl} {sc(s):+.0%}, vol {s.vol_3m:.0%}"
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


def market_ok(snaps: dict[str, Snapshot], benchmark: str = "SPY") -> bool:
    """Marktfilter: de brede markt (benchmark) staat boven haar 200d-gemiddelde."""
    b = snaps.get(benchmark)
    return b is None or b.above_200d is not False


def targets(snaps: dict[str, Snapshot], strat: dict, stock_cap: float,
            crypto_total: float, crypto_cap: float,
            held: set[str] | None = None, sectors: dict[str, str] | None = None,
            benchmark: str = "SPY") -> tuple[dict[str, float], dict[str, str]]:
    invested = strat.get("target_invested_pct", 95) / 100
    why_m = {}
    if strat.get("market_filter") and not market_ok(snaps, benchmark):
        invested = strat.get("bear_invested_pct", 30) / 100
        why_m[benchmark] = f"marktfilter: {benchmark} onder 200d → {invested:.0%} belegd"
    cw, cwhy = crypto_targets(snaps, crypto_total, crypto_cap)
    sc = strat.get("sector_max_pct")
    mv = strat.get("max_vol_pct")
    sw, swhy = stock_targets(snaps, invested - sum(cw.values()), strat.get("stock_top_n", 10),
                             stock_cap, held, strat.get("hold_buffer", 0), sectors,
                             sc / 100 if sc else None, strat.get("score", "mom12"),
                             {benchmark} if strat.get("exclude_benchmark", True) else set(),
                             mv / 100 if mv else None)
    return {**sw, **cw}, {**swhy, **cwhy, **why_m}


def fixed_split(snaps: dict[str, Snapshot], strat: dict, crypto_share: float,
                stock_cap: float) -> dict[str, float]:
    """Schaduw '50/50': vast crypto-deel (zonder trendfilter), rest via aandelenregels."""
    invested = strat.get("target_invested_pct", 95) / 100
    cr = [s for s in snaps.values() if s.crypto]
    cw = _inverse_vol(cr, invested * crypto_share, 1.0)
    sw, _ = stock_targets(snaps, invested * (1 - crypto_share), strat.get("stock_top_n", 10),
                          stock_cap)
    return {**sw, **cw}
