"""Haalt 13F-rapporten (SEC EDGAR) van gekozen investeerders op en zet CUSIP's om naar tickers.

Gebruik: python tools/fetch_investors.py [--since 2025-10-01]
Schrijft naar research/13f.json (posities per fonds per kwartaal) en research/cusip_map.json.

13F toont enkel lange aandelenposities en opties (puts/calls) van Amerikaanse effecten,
gerapporteerd tot 45 dagen na het kwartaaleinde. Shortposities in aandelen staan er niet in.
"""
from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research"
UA = {"User-Agent": "InvestingAgent/1.0 paper-research admin@investing-agent.local"}

INVESTORS = {
    "ARK Invest (Cathie Wood)": "0001697748",
    "Situational Awareness (Leopold Aschenbrenner)": "0002045724",
    "Altimeter (Brad Gerstner)": "0001541617",
    "Coatue (Philippe Laffont)": "0001135730",
    "Tiger Global (Chase Coleman)": "0001167483",
}


def get(url, **kw):
    for i in range(4):
        r = requests.get(url, headers=UA, timeout=30, **kw)
        if r.status_code == 200:
            time.sleep(0.15)  # SEC: max 10 verzoeken/seconde
            return r
        time.sleep(2 * (i + 1))
    r.raise_for_status()


def filings(cik: str, since: str) -> list[dict]:
    d = get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    r = d["filings"]["recent"]
    out = []
    for form, fdate, acc, rdate in zip(r["form"], r["filingDate"], r["accessionNumber"],
                                       r["reportDate"]):
        if form == "13F-HR" and fdate >= since:
            out.append({"filed": fdate, "period": rdate, "accession": acc})
    return sorted(out, key=lambda x: x["period"])


def infotable(cik: str, accession: str) -> list[dict]:
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    idx = get(f"{base}/index.json").json()
    names = [i["name"] for i in idx["directory"]["item"]]
    xmls = [n for n in names if n.lower().endswith(".xml") and "primary_doc" not in n.lower()]
    if not xmls:
        return []
    root = ET.fromstring(get(f"{base}/{xmls[0]}").content)
    rows = []
    for it in root.iter():
        if not it.tag.endswith("infoTable"):
            continue
        f = {c.tag.split("}")[-1]: c for c in it.iter()}
        txt = lambda k: (f[k].text or "").strip() if k in f else ""
        rows.append({"issuer": txt("nameOfIssuer"), "class": txt("titleOfClass"),
                     "cusip": txt("cusip").upper(), "value": float(txt("value") or 0),
                     "shares": float(txt("sshPrnamt") or 0), "type": txt("sshPrnamtType"),
                     "putCall": txt("putCall").upper()})
    return rows


def map_cusips(cusips: set[str], cache: dict, save=None, budget_s: float = 1e9) -> dict:
    todo = [c for c in cusips if c not in cache]
    t0 = time.time()
    for i in range(0, len(todo), 10):
        if time.time() - t0 > budget_s:
            print(f"Tijdsbudget op; {len(todo) - i} CUSIP's resten (opnieuw starten hervat).")
            break
        batch = todo[i:i + 10]
        r = requests.post("https://api.openfigi.com/v3/mapping", timeout=30,
                          json=[{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"}
                                for c in batch])
        if r.status_code == 429:
            time.sleep(30)
            r = requests.post("https://api.openfigi.com/v3/mapping", timeout=30,
                              json=[{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"}
                                    for c in batch])
        r.raise_for_status()
        for c, res in zip(batch, r.json()):
            data = res.get("data") or []
            cache[c] = data[0].get("ticker") if data else None
        if save:
            save(cache)
        time.sleep(2.6)  # zonder API-key: 25 verzoeken per minuut
    return cache


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-10-01", help="ingediend vanaf (incl. Q3 2025 als basis)")
    ap.add_argument("--budget", type=float, default=1e9, help="max seconden voor tickeromzetting")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    raw_p, cache_p = OUT / "13f_raw.json", OUT / "cusip_map.json"
    if raw_p.exists():
        result = json.loads(raw_p.read_text())
        print("SEC-data al opgehaald (research/13f_raw.json)")
    else:
        result = {}
        for name, cik in INVESTORS.items():
            fl = filings(cik, a.since)
            print(f"{name}: {len(fl)} rapporten")
            for f in fl:
                rows = infotable(cik, f["accession"])
                agg = {}  # samenvoegen per cusip + putCall
                for r in rows:
                    k = f"{r['cusip']}|{r['putCall']}"
                    if k not in agg:
                        agg[k] = dict(r)
                    else:
                        agg[k]["value"] += r["value"]
                        agg[k]["shares"] += r["shares"]
                f["holdings"] = list(agg.values())
                f["total_value"] = sum(h["value"] for h in f["holdings"] if not h["putCall"])
                print(f"  {f['period']} (ingediend {f['filed']}): {len(f['holdings'])} posities, "
                      f"${f['total_value'] / 1e9:,.2f} mld long")
            result[name] = fl
        raw_p.write_text(json.dumps(result))
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    cusips = {h["cusip"] for fl in result.values() for f in fl for h in f["holdings"]}
    print(f"CUSIP's omzetten naar tickers: {len([c for c in cusips if c not in cache])} te doen")
    map_cusips(cusips, cache, save=lambda c: cache_p.write_text(json.dumps(c, indent=1, sort_keys=True)),
               budget_s=a.budget)
    if any(c not in cache for c in cusips):
        return
    for fl in result.values():
        for f in fl:
            for h in f["holdings"]:
                h["ticker"] = cache.get(h["cusip"])
    (OUT / "13f.json").write_text(json.dumps(result, indent=1))
    print("Klaar: research/13f.json")


if __name__ == "__main__":
    main()
