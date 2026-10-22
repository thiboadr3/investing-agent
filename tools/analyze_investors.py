"""Analyseert research/13f.json: wat deden de fondsen, en wat had kopiëren opgeleverd?

Kopieertest (realistisch): op de eerste beursdag NA de indiening van een 13F koop je de
top-10 lange aandelenposities van dat fonds (gewogen naar hun gewicht), en je houdt die tot
de volgende indiening. Zo reken je met de echte vertraging van tot 45 dagen.
Vergeleken met SPY over exact dezelfde periode. Geen kosten/belasting meegerekend.

Gebruik: python tools/analyze_investors.py  -> research/investors_report.md
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.enums import Adjustment  # noqa: E402
from alpaca.data.requests import StockBarsRequest  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402

from agent import config  # noqa: E402

TOP = 10


def longs(filing):
    """Enkel lange aandelenposities (geen puts/calls), samengevoegd per ticker."""
    agg = defaultdict(float)
    for h in filing["holdings"]:
        if h["putCall"] or not h.get("ticker") or h["type"] not in ("SH", ""):
            continue
        agg[h["ticker"].replace("/", ".")] += h["value"]
    tot = sum(agg.values()) or 1
    return {t: v / tot for t, v in sorted(agg.items(), key=lambda kv: -kv[1])}


def options(filing):
    out = defaultdict(float)
    for h in filing["holdings"]:
        if h["putCall"] and h.get("ticker"):
            out[(h["ticker"], h["putCall"])] += h["value"]
    return out


def prices(tickers, start):
    cfg = config.load()
    cl = StockHistoricalDataClient(cfg.alpaca_key, cfg.alpaca_secret)
    out = {}
    tick = sorted(set(tickers))
    for i in range(0, len(tick), 50):
        req = StockBarsRequest(symbol_or_symbols=tick[i:i + 50], timeframe=TimeFrame.Day,
                               start=start, adjustment=Adjustment.ALL)
        for s, rows in cl.get_stock_bars(req).data.items():
            out[s] = {b.timestamp.date().isoformat(): float(b.close) for b in rows}
    return out


def px_on_or_after(series, day):
    for d in sorted(series):
        if d > day:          # eerste beursdag NA indiening
            return d, series[d]
    return None, None


def last_px(series):
    d = max(series)
    return d, series[d]


def main():
    data = json.loads((ROOT / "research" / "13f.json").read_text())
    md = ["# Wat deden de AI-investeerders in 2026?", "",
          f"_Bron: SEC 13F-rapporten. Gegenereerd {datetime.now(timezone.utc):%Y-%m-%d}._", ""]
    needed, plans = {"SPY"}, {}
    latest_w = {}
    for name, fl in data.items():
        md += [f"## {name}", ""]
        prev = None
        for f in fl:
            w = longs(f)
            top = list(w.items())[:TOP]
            md.append(f"**Kwartaal t.e.m. {f['period']}** (ingediend {f['filed']}, "
                      f"${f['total_value'] / 1e9:,.1f} mld lang) — top {TOP}: "
                      + ", ".join(f"{t} {x:.0%}" for t, x in top))
            if prev is not None:
                new = [t for t in list(w)[:25] if t not in prev]
                gone = [t for t in list(prev)[:25] if t not in w]
                up = sorted(((t, w[t] - prev.get(t, 0)) for t in w if t in prev),
                            key=lambda kv: -kv[1])[:5]
                md.append(f"- Nieuw in top 25: {', '.join(new[:8]) or '—'}")
                md.append(f"- Volledig verkocht (uit vorige top 25): {', '.join(gone[:8]) or '—'}")
                md.append("- Grootste gewichtsstijgers: "
                          + ", ".join(f"{t} {d:+.1%}" for t, d in up if d > 0))
            opts = options(f)
            if opts:
                big = sorted(opts.items(), key=lambda kv: -kv[1])[:6]
                md.append("- Opties (geen gewone posities!): "
                          + ", ".join(f"{t} {pc}" for (t, pc), v in big))
            md.append("")
            prev = w
            if f["filed"] >= "2026-01-01":
                plans.setdefault(name, []).append((f["filed"], dict(top)))
                needed |= {t for t, _ in top}
        latest_w[name] = longs(fl[-1])

    # consensus in het laatste kwartaal
    md += ["## Consensus (laatste rapport): aandelen bij meerdere fondsen in de top 25", ""]
    cnt, wsum = defaultdict(list), defaultdict(float)
    for name, w in latest_w.items():
        for t, x in list(w.items())[:25]:
            cnt[t].append(name.split(" (")[0])
            wsum[t] += x
    cons = sorted([t for t in cnt if len(cnt[t]) >= 2], key=lambda t: (-len(cnt[t]), -wsum[t]))
    for t in cons[:20]:
        md.append(f"- **{t}** — {len(cnt[t])} fondsen ({', '.join(cnt[t])}), "
                  f"gem. gewicht {wsum[t] / len(cnt[t]):.1%}")
    needed |= set(cons[:20])
    md.append("")

    # kopieertest 2026
    start = datetime(2026, 1, 15, tzinfo=timezone.utc)
    px = prices(needed, start)
    spy = px.get("SPY", {})
    md += ["## Kopieertest 2026: top 10 kopiëren op de dag na elke indiening", "",
           "| Fonds | Periode | Kopie top 10 | SPY zelfde periode | Verschil |",
           "|---|---|---:|---:|---:|"]
    summary = []
    for name, steps in plans.items():
        value, spy_v, first_day, last_day = 1.0, 1.0, None, None
        for i, (filed, top) in enumerate(steps):
            d0, s0 = px_on_or_after(spy, filed)
            if not d0:
                continue
            end = steps[i + 1][0] if i + 1 < len(steps) else None
            d1, s1 = px_on_or_after(spy, end) if end else last_px(spy)
            tot_w, ret = 0.0, 0.0
            for t, x in top.items():
                ser = px.get(t)
                if not ser:
                    continue
                a = ser.get(d0) or px_on_or_after(ser, filed)[1]
                b = ser.get(d1) or (px_on_or_after(ser, end)[1] if end else last_px(ser)[1])
                if a and b:
                    ret += x * (b / a - 1)
                    tot_w += x
            if tot_w:
                value *= 1 + ret / tot_w
                spy_v *= s1 / s0
            first_day = first_day or d0
            last_day = d1
        if first_day:
            summary.append((name, value - 1, spy_v - 1))
            md.append(f"| {name} | {first_day} → {last_day} | {value - 1:+.1%} | "
                      f"{spy_v - 1:+.1%} | {value - spy_v:+.1%} |")
    md += ["", "_Let op: verleden rendement zegt niets over de toekomst; 1 jaar is een kleine "
           "steekproef; kosten, belasting en wisselkoers niet meegerekend._", ""]

    # wat opvalt over de 5 heen
    md += ["## Thema's (laatste rapport, gewogen top 25 over alle fondsen)", ""]
    theme = defaultdict(float)
    for w in latest_w.values():
        for t, x in list(w.items())[:25]:
            theme[t] += x / len(latest_w)
    md.append(", ".join(f"{t} {x:.1%}" for t, x in sorted(theme.items(), key=lambda kv: -kv[1])[:25]))
    (ROOT / "research" / "investors_report.md").write_text("\n".join(md))
    (ROOT / "research" / "investors_summary.json").write_text(json.dumps(
        {"copy_test": [{"fund": n, "copy": c, "spy": s} for n, c, s in summary],
         "consensus": [{"ticker": t, "funds": cnt[t], "avg_weight": wsum[t] / len(cnt[t])}
                       for t in cons[:20]]}, indent=1))
    print("\n".join(md))


if __name__ == "__main__":
    main()
