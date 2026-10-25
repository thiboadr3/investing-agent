"""Eerlijke backtest: S&P 500 zónder overlevingsbias.

Op elke dag mag de strategie enkel kiezen uit de aandelen die op dat moment in de S&P 500
zaten (historische samenstelling, bron: github.com/fja05680/sp500, MIT). Aandelen die later
uit de index vielen of verdwenen, zitten er dus gewoon in. Zelfde regels als de agent.

Gebruik:
  python tools/backtest_sp500.py fetch [--budget 150]   koersen ophalen (Alpaca), hervatbaar
  python tools/backtest_sp500.py run                    varianten -> research/backtest_sp500.md

Beperkingen (eerlijk):
  - koersen van verdwenen tickers ontbreken soms bij Alpaca (dekking staat in het rapport);
  - een verdwenen aandeel wordt gewaardeerd aan zijn laatste koers (bij overnames meestal
    te laag, bij faillissementen te hoog);
  - sectorindeling is die van vandaag; onbekende sector = eigen sector.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import backtest as B  # noqa: E402

HIST = ROOT / "research" / "sp500_hist.csv"
PDIR = ROOT / "data" / "sp500_prices"
HIST_URL = ("https://raw.githubusercontent.com/fja05680/sp500/master/"
            "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv")


def membership():
    rows = list(csv.reader(open(HIST)))[1:]
    return [(d, set(t.split(","))) for d, t in rows]


def all_tickers(since="2015-01-01"):
    u = set()
    for d, s in membership():
        if d >= since:
            u |= s
    return sorted(u)


def fetch(budget=150.0):
    from alpaca.data.enums import Adjustment
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    from agent import config
    cfg = config.load()
    cl = StockHistoricalDataClient(cfg.alpaca_key, cfg.alpaca_secret)
    PDIR.mkdir(parents=True, exist_ok=True)
    syms = all_tickers() + ["SPY"]
    t0 = time.time()
    batches = [syms[i:i + 40] for i in range(0, len(syms), 40)]
    for k, batch in enumerate(batches):
        f = PDIR / f"batch_{k:03d}.json"
        if f.exists():
            continue
        if time.time() - t0 > budget:
            print("Tijdsbudget op; opnieuw starten hervat.")
            return
        out = {}
        try:
            req = StockBarsRequest(symbol_or_symbols=batch, timeframe=TimeFrame.Day,
                                   start=datetime(2015, 1, 2, tzinfo=timezone.utc),
                                   adjustment=Adjustment.ALL)
            data = cl.get_stock_bars(req).data
        except Exception as e:  # één ongeldig symbool kan een batch laten falen: per stuk
            print(f"batch {k}: {e!s:.80}; per symbool")
            data = {}
            for s in batch:
                try:
                    req = StockBarsRequest(symbol_or_symbols=s, timeframe=TimeFrame.Day,
                                           start=datetime(2015, 1, 2, tzinfo=timezone.utc),
                                           adjustment=Adjustment.ALL)
                    data.update(cl.get_stock_bars(req).data)
                except Exception:
                    pass
        for s, rows in data.items():
            out[s] = {r.timestamp.date().isoformat(): [float(r.open), float(r.close)]
                      for r in rows}
        f.write_text(json.dumps(out))
        print(f"batch {k + 1}/{len(batches)}: {len(out)} met data")
    print("Klaar met ophalen.")


def load():
    raw = {}
    for f in sorted(PDIR.glob("batch_*.json")):
        raw.update(json.loads(f.read_text()))
    days = sorted(raw["SPY"])
    syms = sorted(s for s in raw if s != "SPY")
    idx = {d: i for i, d in enumerate(days)}
    o = np.full((len(days), len(syms)), np.nan)
    c = np.full((len(days), len(syms)), np.nan)
    for j, s in enumerate(syms):
        for d, (op, cl) in raw[s].items():
            if d in idx:
                o[idx[d], j], c[idx[d], j] = op, cl
    # na de laatste koers: laatste koers aanhouden (verdwenen aandeel), niet op 0 zetten
    for j in range(len(syms)):
        col_c, col_o = c[:, j], o[:, j]
        valid = np.where(~np.isnan(col_c))[0]
        if len(valid):
            last = valid[-1]
            col_c[last + 1:] = col_c[last]
            col_o[last + 1:] = col_c[last]
            for arr in (col_c, col_o):        # gaten binnen de reeks opvullen
                for i in range(valid[0] + 1, last + 1):
                    if np.isnan(arr[i]):
                        arr[i] = arr[i - 1]
    spy = np.array([raw["SPY"][d][1] for d in days])
    # leden per dag (laatste samenstelling op of vóór die dag); ticker 'BRK.B' notatie gelijk
    mem = membership()
    members, k = [], 0
    for d in days:
        while k + 1 < len(mem) and mem[k + 1][0] <= d:
            k += 1
        members.append(mem[k][1])
    return days, syms, o, c, spy, members, raw


def run():
    days, syms, o, c, spy, members, raw = load()
    from agent import config
    sectors = config.load().sectors
    need = set().union(*[m for d, m in zip(days, members) if d >= "2017-01-03"])
    have = need & set(syms)
    V = B.Variant
    variants = [
        V("Top 10, max 10% + buffer + band 3%", buffer=10, band=0.03),
        V("Top 10 + sectorlimiet 25%", buffer=10, band=0.03, sector_cap=0.25),
        V("Top 10 + sectorlimiet + marktfilter", buffer=10, band=0.03, sector_cap=0.25,
          market_filter=True),
        V("Top 5, max 20% + buffer + band 3%", top_n=5, cap=0.20, buffer=5, band=0.03),
        V("Top 5, max 20% + sectorlimiet 40%", top_n=5, cap=0.20, buffer=5, band=0.03,
          sector_cap=0.40),
        V("Top 5 + sectorlimiet + marktfilter", top_n=5, cap=0.20, buffer=5, band=0.03,
          sector_cap=0.40, market_filter=True),
        V("Top 20, max 5% + buffer + band 2%", top_n=20, cap=0.05, buffer=20, band=0.02),
    ]
    periods = [("Volledig 2017–2026", "2017-01-03", "2099"),
               ("Deel 1 (2017–2022)", "2017-01-03", "2022-12-31"),
               ("Deel 2, ongezien (2023–2026)", "2023-01-03", "2099")]
    md = ["# Eerlijke backtest: S&P 500 zonder overlevingsbias", "",
          f"_Gegenereerd {datetime.now(timezone.utc):%Y-%m-%d}. Elke dag enkel aandelen die toen in "
          "de S&P 500 zaten. Zelfde regels als de agent; uitvoering op opening volgende dag; "
          "kosten 0,05% per transactie; start $10.000; pauzeregel −15% met reset._", "",
          f"Koersdekking: {len(have)} van {len(need)} tickers die sinds 2017 in de index zaten "
          f"({len(have) / len(need):.0%}). Ontbrekende tickers (meestal verdwenen of hernoemd) "
          "kunnen niet gekozen worden.", ""]
    results = {}
    for pname, a, b in periods:
        md += [f"## {pname}", "",
               "| Variant | Totaal | Per jaar | Max. daling | Sharpe | Kosten | Omzet/jaar |",
               "|---|---:|---:|---:|---:|---:|---:|"]
        si = next(i for i, d in enumerate(days) if d >= a)
        ei = next((i for i, d in enumerate(days) if d > b), len(days))
        for v in variants + ["SPY"]:
            if v == "SPY":
                vals = 10_000 * spy[si:ei - 1] / spy[si]
                s, label, cost_s, turn_s = B.stats(vals, days[si:ei - 1]), "**SPY kopen en houden**", "$0", "—"
            else:
                t0 = time.time()
                vals, costs, turn = B.simulate(v, days, syms, o, c, spy, si, ei,
                                               members=members, sectors=sectors)
                s = B.stats(vals, days[si:si + len(vals)])
                label = v.name
                yrs = len(vals) / 252
                cost_s, turn_s = f"${costs:,.0f}", f"{turn / 10_000 / yrs:.1f}×"
                print(f"  {pname} | {label}: {s['cagr']:+.1%}/jaar ({time.time() - t0:.0f}s)")
            results[(pname, label)] = s
            md.append(f"| {label} | {s['total']:+.0%} | {s['cagr']:+.1%} | −{s['mdd']:.0%} | "
                      f"{s['sharpe']:.2f} | {cost_s} | {turn_s} |")
        md.append("")
    full = [(k[1], v) for k, v in results.items() if k[0] == periods[0][0]]
    years = sorted(full[0][1]["yearly"])
    md += ["## Rendement per jaar (volledige periode)", "",
           "| Variant | " + " | ".join(years) + " |", "|---|" + "---:|" * len(years)]
    for label, s in full:
        md.append(f"| {label} | " + " | ".join(f"{s['yearly'].get(y, 0):+.0%}" for y in years) + " |")
    out = ROOT / "research" / "backtest_sp500.md"
    out.write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "fetch":
        b = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 150
        fetch(b)
    else:
        run()
