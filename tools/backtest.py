"""Backtest van de regelstrategie met EXACT dezelfde regels als de agent (agent/rules.py).

Werking per beursdag t:
  - plan op basis van slotkoersen t/m dag t (zoals het onderzoek vóór de opening)
  - uitvoering op de OPENINGSkoers van dag t+1, met kosten per transactie
  - herbalanceren enkel als het verschil >= min_order (zoals live)
  - pauzeregel: geen aankopen bij >= max_dd vanaf de piek; na `pause_days` beursdagen
    wordt de piek gereset (anders blijft een portefeuille in cash eeuwig geblokkeerd)

Gebruik:
  python tools/backtest.py fetch            # koersen ophalen (Alpaca) -> data/prices.json
  python tools/backtest.py run              # varianten draaien -> research/backtest_report.md

Let op: de aandelenlijst is van VANDAAG gekozen (overlevingsbias: bedrijven die het slecht
deden of verdwenen, zitten er niet in). Resultaten zijn daardoor optimistisch.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import rules  # noqa: E402
from agent.data import Snapshot  # noqa: E402

PRICES = ROOT / "data" / "prices.json"

# Uitbreiding om te testen: grote, liquide aandelen (o.a. AI-infrastructuur en tech).
# Opgelet: deze lijst is met kennis van vandaag gekozen -> extra optimistisch.
EXTRA = ["MU", "LRCX", "AMAT", "KLAC", "TSM", "AMD", "ORCL", "CRM", "NFLX", "TSLA",
         "INTC", "QCOM", "TXN", "CSCO", "IBM", "NOW", "INTU", "ISRG", "CAT", "GE",
         "BA", "HON", "UNP", "GS", "MS", "BAC", "C", "AXP", "BLK", "SCHW",
         "MRK", "PFE", "ABBV", "TMO", "ABT", "MCD", "NKE", "SBUX", "LOW", "TGT",
         "DIS", "CMCSA", "T", "VZ", "NEE", "DUK", "LIN", "DE", "UPS", "PLD"]


# ---------------------------------------------------------------- data
def fetch():
    from alpaca.data.enums import Adjustment
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    from agent import config
    cfg = config.load()
    cl = StockHistoricalDataClient(cfg.alpaca_key, cfg.alpaca_secret)
    syms = sorted(set(cfg.universe) | set(EXTRA) | {"SPY"})
    out = {}
    for i in range(0, len(syms), 40):
        req = StockBarsRequest(symbol_or_symbols=syms[i:i + 40], timeframe=TimeFrame.Day,
                               start=datetime(2015, 1, 2, tzinfo=timezone.utc),
                               adjustment=Adjustment.ALL)
        for s, rows in cl.get_stock_bars(req).data.items():
            out[s] = {r.timestamp.date().isoformat(): [float(r.open), float(r.close)] for r in rows}
        print(f"{min(i + 40, len(syms))}/{len(syms)} symbolen")
    PRICES.parent.mkdir(exist_ok=True)
    PRICES.write_text(json.dumps(out))
    print(f"Opgeslagen: {PRICES} ({len(out)} symbolen)")


def load_matrix(symbols):
    raw = json.loads(PRICES.read_text())
    days = sorted(raw["SPY"])
    syms = [s for s in symbols if s in raw]
    o = np.full((len(days), len(syms)), np.nan)
    c = np.full((len(days), len(syms)), np.nan)
    idx = {d: i for i, d in enumerate(days)}
    for j, s in enumerate(syms):
        for d, (op, cl) in raw[s].items():
            if d in idx:
                o[idx[d], j], c[idx[d], j] = op, cl
    spy = np.array([raw["SPY"][d][1] for d in days])
    spy_o = np.array([raw["SPY"][d][0] for d in days])
    return days, syms, o, c, spy, spy_o


# ---------------------------------------------------------------- indicatoren (zoals build_snapshot)
def indicators(c, sma_days=200, mom_days=252, skip=21):
    T, N = c.shape
    ret = np.full((T, N), np.nan)
    ret[1:] = c[1:] / c[:-1] - 1
    r3m = np.full((T, N), np.nan)
    r3m[63:] = c[63:] / c[:-63] - 1
    mom = np.full((T, N), np.nan)
    mom[mom_days:] = c[mom_days - skip:T - skip] / c[:T - mom_days] - 1
    csum = np.nancumsum(np.nan_to_num(c), axis=0)
    sma = np.full((T, N), np.nan)
    sma[sma_days - 1:] = (csum[sma_days - 1:] - np.vstack([np.zeros((1, N)), csum[:-sma_days]])) / sma_days
    sq = np.nan_to_num(ret) ** 2
    csq = np.cumsum(sq, axis=0)
    vol = np.full((T, N), np.nan)
    vol[63:] = np.sqrt((csq[63:] - csq[:-63]) / 63 * 252)
    above = c > sma
    return {"r3m": r3m, "mom": mom, "above": above, "vol": vol, "sma_ok": ~np.isnan(sma)}


# ---------------------------------------------------------------- simulatie
@dataclass
class Variant:
    name: str
    top_n: int = 10
    cap: float = 0.10
    invested: float = 0.95
    sma_days: int = 200
    mom_days: int = 252
    rebalance: str = "daily"      # daily | weekly | monthly
    extra: bool = False
    max_dd: float = 0.15
    pause_days: int = 20
    cost: float = 0.0005
    min_order: float = 100.0
    band: float = 0.0             # enkel bijsturen als afwijking > band × portefeuille (bv. 0.03)
    buffer: int = 0               # houd bestaande posities zolang ze in top (N + buffer) staan


def simulate(v: Variant, days, syms, o, c, spy, start_i, end_i, start_value=10_000.0):
    ind = indicators(c, v.sma_days, v.mom_days)
    N = len(syms)
    cash, qty = start_value, np.zeros(N)
    peak, pause_left = start_value, 0
    values, costs, turnover = [], 0.0, 0.0
    last_period = None
    for t in range(start_i, end_i - 1):
        # waarde op slot t
        px = np.nan_to_num(c[t])
        val = cash + float(qty @ px)
        values.append(val)
        if pause_left > 0:
            pause_left -= 1
            if pause_left == 0:
                peak = val                       # piek resetten na de pauze
        peak = max(peak, val)
        dd = 1 - val / peak
        if dd >= v.max_dd and pause_left == 0:
            pause_left = v.pause_days
        allow_buys = dd < v.max_dd and pause_left == 0

        d = days[t]
        period = d[:7] if v.rebalance == "monthly" else (
            datetime.fromisoformat(d).isocalendar()[1] if v.rebalance == "weekly" else d)
        if period == last_period:
            continue
        last_period = period

        snaps = {}
        for j, s in enumerate(syms):
            if np.isnan(c[t, j]) or not ind["sma_ok"][t, j]:
                continue
            snaps[s] = Snapshot(s, c[t, j], None, None,
                                None if np.isnan(ind["r3m"][t, j]) else ind["r3m"][t, j],
                                None, bool(ind["above"][t, j]),
                                None if np.isnan(ind["vol"][t, j]) else ind["vol"][t, j],
                                None if np.isnan(ind["mom"][t, j]) else ind["mom"][t, j], False)
        held = {syms[j] for j in range(N) if qty[j] > 1e-9}
        w, _ = rules.stock_targets(snaps, v.invested, v.top_n, v.cap, held, v.buffer)

        # uitvoering op opening t+1: eerst verkopen, dan kopen
        op = o[t + 1]
        val_o = cash + float(np.nansum(qty * np.nan_to_num(op)))
        orders = []
        for j, s in enumerate(syms):
            if np.isnan(op[j]):
                continue
            cur = qty[j] * op[j]
            diff = w.get(s, 0) * val_o - cur
            if w.get(s, 0) == 0 and cur > 0:
                diff = -cur
            elif abs(diff) < max(v.min_order, v.band * val_o) and not (cur == 0 and diff > 0):
                continue
            orders.append((diff, j))
        for diff, j in sorted(orders):          # negatieve eerst (verkopen)
            if diff > 0 and not allow_buys:
                continue
            amt = min(abs(diff), cash / (1 + v.cost)) if diff > 0 else abs(diff)
            if amt < 1:
                continue
            fee = amt * v.cost
            if diff > 0:
                qty[j] += amt / op[j]
                cash -= amt + fee
            else:
                qty[j] -= amt / op[j]
                cash += amt - fee
            costs += fee
            turnover += amt
    return np.array(values), costs, turnover


def stats(values, days_used, start_value=10_000.0):
    if len(values) < 2:
        return {}
    r = values[1:] / values[:-1] - 1
    years = len(values) / 252
    cagr = (values[-1] / start_value) ** (1 / years) - 1
    peak = np.maximum.accumulate(values)
    mdd = float(np.max(1 - values / peak))
    sharpe = float(np.mean(r) / np.std(r) * math.sqrt(252)) if np.std(r) > 0 else 0
    yearly = {}
    for d, v in zip(days_used, values):
        yearly.setdefault(d[:4], [v, v])[1] = v
    prev = start_value
    yr = {}
    for y in sorted(yearly):
        yr[y] = yearly[y][1] / prev - 1
        prev = yearly[y][1]
    return {"total": values[-1] / start_value - 1, "cagr": cagr, "mdd": mdd, "sharpe": sharpe,
            "vol": float(np.std(r) * math.sqrt(252)), "yearly": yr, "end": float(values[-1])}


def run():
    from agent import config
    base = list(config.load().universe)
    variants = [
        Variant("Huidig (top 10, max 10%, dagelijks)"),
        Variant("Geconcentreerd (top 5, max 20%)", top_n=5, cap=0.20),
        Variant("Maandelijks herbalanceren", rebalance="monthly"),
        Variant("Sneller (100d-trend, 6m-momentum)", sma_days=100, mom_days=126),
        Variant("Breder universum (+50 large caps)", extra=True),
        Variant("Breder + geconcentreerd (top 5, max 20%)", extra=True, top_n=5, cap=0.20),
        Variant("Huidig + buffer 10 + band 3%", buffer=10, band=0.03),
        Variant("Top 5, max 20% + buffer 5 + band 3%", top_n=5, cap=0.20, buffer=5, band=0.03),
        Variant("Breder, top 10 + buffer 10 + band 3%", extra=True, buffer=10, band=0.03),
        Variant("Breder, top 5, max 20% + buffer 5 + band 3%", extra=True, top_n=5, cap=0.20,
                buffer=5, band=0.03),
    ]
    periods = [("Volledig 2017–2026", "2017-01-03", "2099"),
               ("Deel 1 (2017–2022)", "2017-01-03", "2022-12-31"),
               ("Deel 2, ongezien (2023–2026)", "2023-01-03", "2099")]
    md = ["# Backtest regelstrategie", "",
          f"_Gegenereerd {datetime.now(timezone.utc):%Y-%m-%d}. Dezelfde regels als de agent "
          "(`agent/rules.py`); plan op slotkoers, uitvoering op opening volgende dag; kosten 0,05% "
          "per transactie; startbedrag $10.000; pauzeregel −15% met reset na 20 beursdagen._", "",
          "**Waarschuwing:** de aandelenlijsten zijn met kennis van vandaag gekozen (overlevingsbias), "
          "dus de resultaten zijn optimistisch. Dividenden zitten in de koersen (gecorrigeerd).", ""]
    results = {}
    for pname, a, b in periods:
        md += [f"## {pname}", "",
               "| Variant | Totaal | Per jaar | Max. daling | Sharpe | Kosten | Omzet/jaar |",
               "|---|---:|---:|---:|---:|---:|---:|"]
        for v in variants + ["SPY"]:
            symbols = base + (EXTRA if (v != "SPY" and v.extra) else [])
            days, syms, o, c, spy, spy_o = load_matrix(symbols)
            si = next(i for i, d in enumerate(days) if d >= a)
            ei = next((i for i, d in enumerate(days) if d > b), len(days))
            if v == "SPY":
                vals = 10_000 * spy[si:ei - 1] / spy[si]
                s, label, cost_s, turn_s = stats(vals, days[si:ei - 1]), "**SPY kopen en houden**", "$0", "—"
            else:
                vals, costs, turn = simulate(v, days, syms, o, c, spy, si, ei)
                s = stats(vals, days[si:si + len(vals)])
                label = v.name
                yrs = len(vals) / 252
                cost_s, turn_s = f"${costs:,.0f}", f"{turn / 10_000 / yrs:.1f}×"
            results[(pname, label)] = s
            md.append(f"| {label} | {s['total']:+.0%} | {s['cagr']:+.1%} | −{s['mdd']:.0%} | "
                      f"{s['sharpe']:.2f} | {cost_s} | {turn_s} |")
        md.append("")
    # rendement per jaar (volledige periode)
    full = [(k[1], v) for k, v in results.items() if k[0] == periods[0][0]]
    years = sorted(full[0][1]["yearly"])
    md += ["## Rendement per jaar (volledige periode)", "",
           "| Variant | " + " | ".join(years) + " |", "|---|" + "---:|" * len(years)]
    for label, s in full:
        md.append(f"| {label} | " + " | ".join(f"{s['yearly'].get(y, 0):+.0%}" for y in years) + " |")
    md.append("")
    out = ROOT / "research" / "backtest_report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    {"fetch": fetch, "run": run}[sys.argv[1] if len(sys.argv) > 1 else "run"]()
