"""Investing Agent — paper trading.

Gebruik:
  python -m agent status                 rekening, posities, terugval
  python -m agent once --dry-run         één analyse, orders enkel loggen
  python -m agent once --dry-run --ignore-market-hours   idem, ook als beurs dicht is
  python -m agent once                   één analyse en echte PAPER-orders
  python -m agent tick [--dry-run]       één korte doorloop (voor GitHub Actions)
  python -m agent run                    doorlopend (voor een eigen server)

Noodstop: maak een leeg bestand 'STOP' in de projectmap. Verwijder het om te hervatten.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import ai, config, risk, strategy
from .broker import Broker
from .data import MarketData
from .db import DB, now

NY = ZoneInfo("America/New_York")
SESSION_MIN = 390  # reguliere sessie 9:30–16:00 ET


class Agent:
    def __init__(self, cfg: config.Config):
        self.cfg = cfg
        self.db = DB(config.DB_PATH)
        self.broker = Broker(cfg.alpaca_key, cfg.alpaca_secret)
        self.data = MarketData(cfg.alpaca_key, cfg.alpaca_secret)
        self._analyst = None

    @property
    def analyst(self):
        if self._analyst is None:
            self._analyst = ai.Analyst(self.cfg.gemini_key, self.cfg.ai["model"],
                                       self.cfg.ai["temperature"],
                                       self.cfg.ai.get("fallback_models", []))
            self._analyst.before_call = self._ai_budget_check
        return self._analyst

    def _ai_budget_check(self):
        """Harde limiet op het aantal AI-aanroepen per dag (kostenrem)."""
        today = datetime.now(NY).strftime("%Y%m%d")
        n = self.db.get(f"ai_calls_{today}", 0)
        limit = self.cfg.ai.get("max_calls_per_day", 12)
        if n >= limit:
            raise RuntimeError(f"Kostenrem: max {limit} AI-aanroepen per dag bereikt")
        month = datetime.now(NY).strftime("%Y%m")
        spent = self.db.get(f"ai_cost_{month}", 0)
        cap = self.cfg.ai.get("max_cost_per_month_usd", 5)
        if spent >= cap:
            raise RuntimeError(f"Kostenrem: maandbudget ${cap} bereikt (${spent:.2f})")
        self.db.set(f"ai_calls_{today}", n + 1)

    def _ai_cost(self, usage: dict) -> float:
        p = self.cfg.ai.get("price_per_mtok", {"input": 0.75, "output": 3.75})
        return usage["input"] / 1e6 * p["input"] + usage["output"] / 1e6 * p["output"]

    # ---------- opvolging ----------
    def snapshot(self):
        acct = self.broker.account()
        pos = self.broker.positions()
        peak = max(self.db.get("peak_equity", acct.equity), acct.equity)
        self.db.set("peak_equity", peak)
        self.db.x("INSERT INTO snapshots VALUES (?,?,?,?,?)",
                  (now(), acct.equity, acct.cash, peak,
                   json.dumps({s: p.market_value for s, p in pos.items()})))
        return acct, pos, peak

    def reconcile(self):
        """Vergelijk lokaal logboek met de broker en werk orderstatus bij."""
        rows = self.db.x("SELECT client_order_id, status FROM orders WHERE status IN "
                         "('submitted','new','accepted','pending_new','partially_filled')").fetchall()
        for cid, old in rows:
            o = self.broker.order_by_client_id(cid)
            if o is None:
                self.db.event("WARN", f"Order {cid} niet gevonden bij broker")
                continue
            new = str(o.status.value if hasattr(o.status, "value") else o.status)
            if new != old:
                self.db.x("UPDATE orders SET status=?, qty=? WHERE client_order_id=?",
                          (new, float(o.filled_qty or 0), cid))
                self.db.event("INFO", f"Order {cid}: {old} -> {new}")

    def store_news(self, items: list[dict]):
        for n in items:
            self.db.x("INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?,?,?)",
                      (str(n.get("id")), now(), n.get("created_at"),
                       ",".join(n.get("symbols", [])), n.get("headline"),
                       n.get("summary"), n.get("source"), n.get("url")))

    # ---------- analyse + handel ----------
    def analyse_and_trade(self, dry_run: bool, ignore_hours: bool = False):
        cfg, r = self.cfg, self.cfg.risk
        cycle_id = datetime.now(NY).strftime("%Y%m%d")  # één analyse per beursdag
        acct, pos, peak = self.snapshot()
        clock = self.broker.market_clock()
        universe = list(cfg.universe)

        snaps = self.data.snapshots(universe)
        news = self.data.news(universe, cfg.ai["news_lookback_hours"])
        self.store_news(news)

        prompt = ai.build_prompt(snaps, pos, acct.equity, news, r.max_position_pct / 100)
        try:
            raw = self.analyst.analyse(prompt)
            decisions = ai.parse(raw, set(universe), r.max_position_pct / 100)
            u = self.analyst.last_usage
            cost = self._ai_cost(u)
            self.db.set("ai_cost_total_usd", round(self.db.get("ai_cost_total_usd", 0) + cost, 4))
            mkey = f"ai_cost_{datetime.now(NY).strftime('%Y%m')}"
            self.db.set(mkey, round(self.db.get(mkey, 0) + cost, 4))
            self.db.event("INFO", f"AI-model {self.analyst.last_model}: {u['input']} in / "
                                  f"{u['output']} uit tokens ≈ ${cost:.4f}", u)
        except Exception as e:  # quota, netwerk, ongeldige JSON -> niets doen
            self.db.event("ERROR", "AI-analyse mislukt; geen beslissingen", str(e))
            return

        for d in decisions:
            self.db.x("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?)",
                      (now(), cycle_id, d["symbol"], d["action"], d["target_weight"],
                       d["confidence"], json.dumps(d["reasons_for"], ensure_ascii=False),
                       json.dumps(d["reasons_against"], ensure_ascii=False), raw))

        values = {s: p.market_value for s, p in pos.items()}
        ctx = risk.Context(
            equity=acct.equity, cash=acct.cash, peak_equity=peak,
            position_values=dict(values), position_qty={s: p.qty for s, p in pos.items()},
            open_order_symbols=self.broker.open_order_symbols(), universe=set(universe),
            orders_today=self.db.orders_today(),
            market_open=bool(clock.is_open) or (dry_run and ignore_hours),
            account_ok=(not acct.trading_blocked and acct.status.endswith("ACTIVE")),
            stop_file=config.STOP_FILE.exists(),
            price_as_of={s: v.as_of for s, v in snaps.items()})

        props = strategy.proposals(decisions, acct.equity, values, r.min_order_usd)
        self.db.event("INFO", f"Cyclus {cycle_id}: {len(decisions)} AI-voorstellen, "
                              f"{len(props)} orderkandidaten")

        for p in props:
            cid = f"ia-{cycle_id}-{p.symbol}-{p.side}"
            if self.db.order_exists(cid) or self.broker.order_by_client_id(cid):
                continue  # al uitgevoerd (bv. na herstart)
            rule = risk.check_order(p, ctx, r)
            if rule:
                self.db.x("INSERT INTO rejections VALUES (?,?,?,?,?,?)",
                          (now(), cycle_id, p.symbol, p.side, rule, f"${p.notional:,.0f}"))
                print(f"  geweigerd {p.side} {p.symbol} ${p.notional:,.0f}: {rule}")
                continue

            status, broker_id = "dry_run", None
            if not dry_run:
                held = ctx.position_values.get(p.symbol, 0)
                full_exit = p.side == "sell" and p.notional >= held * 0.99
                try:
                    o = (self.broker.submit(p.symbol, "sell", cid, qty=ctx.position_qty[p.symbol])
                         if full_exit else self.broker.submit(p.symbol, p.side, cid, notional=p.notional))
                    status, broker_id = "submitted", str(o.id)
                except Exception as e:
                    self.db.event("ERROR", f"Order {cid} mislukt", str(e))
                    continue
            self.db.x("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)",
                      (now(), cid, p.symbol, p.side, p.notional, None, status, broker_id,
                       f"conf={p.confidence:.2f}"))
            print(f"  {status}: {p.side} {p.symbol} ${p.notional:,.0f}")

            # context bijwerken zodat volgende checks rekening houden met deze order
            ctx.orders_today += 0 if dry_run else 1
            ctx.open_order_symbols.add(p.symbol)
            if p.side == "buy":
                ctx.cash -= p.notional
                ctx.position_values[p.symbol] = ctx.position_values.get(p.symbol, 0) + p.notional
        self.db.set("last_analysis_dry" if dry_run else "last_analysis", cycle_id)

    # ---------- commando's ----------
    def status(self):
        acct, pos, peak = self.snapshot()
        dd = risk.drawdown_pct(acct.equity, peak)
        print(f"Equity ${acct.equity:,.2f} | cash ${acct.cash:,.2f} | piek ${peak:,.2f} | "
              f"terugval {dd:.1f}% | status {acct.status}")
        for s, p in sorted(pos.items(), key=lambda kv: -kv[1].market_value):
            print(f"  {s:6} {p.qty:>10.4f}  ${p.market_value:>10,.2f}  "
                  f"{p.market_value / acct.equity:>6.1%}")
        month = datetime.now(NY).strftime("%Y%m")
        print(f"Geschatte AI-kosten: deze maand ${self.db.get(f'ai_cost_{month}', 0):.2f} "
              f"(max ${self.cfg.ai.get('max_cost_per_month_usd', 5)}), "
              f"totaal ${self.db.get('ai_cost_total_usd', 0):.2f}")
        if config.STOP_FILE.exists():
            print("NOODSTOP ACTIEF")

    def tick(self, dry_run: bool):
        """Eén korte doorloop, bedoeld voor een planner (GitHub Actions/cron)."""
        clock = self.broker.market_clock()
        if not clock.is_open:
            print(f"Markt gesloten. Volgende opening: {clock.next_open}")
            return
        self.snapshot()
        self.reconcile()
        mins_left = (clock.next_close - clock.timestamp).total_seconds() / 60
        today = datetime.now(NY).strftime("%Y%m%d")
        key = "last_analysis_dry" if dry_run else "last_analysis"
        if self.db.get(key) == today:
            print("Analyse van vandaag is al gebeurd; enkel opvolging.")
        elif mins_left > SESSION_MIN - self.cfg.schedule["analysis_after_open_min"]:
            print("Te vroeg na de opening; analyse volgt bij een volgende run.")
        else:
            self.analyse_and_trade(dry_run=dry_run)

    def run_forever(self):
        sch = self.cfg.schedule
        last_check = last_news = 0.0
        errors = 0
        self.db.event("INFO", "Agent gestart (paper)")
        while True:
            try:
                clock = self.broker.market_clock()
                t = time.time()
                if clock.is_open:
                    if t - last_check >= sch["check_interval_min"] * 60:
                        self.snapshot()
                        self.reconcile()
                        last_check = t
                    mins_left = (clock.next_close - clock.timestamp).total_seconds() / 60
                    today = datetime.now(NY).strftime("%Y%m%d")
                    if (self.db.get("last_analysis") != today
                            and mins_left <= SESSION_MIN - sch["analysis_after_open_min"]):
                        self.analyse_and_trade(dry_run=False)
                elif t - last_news >= sch["news_interval_min"] * 60:
                    self.store_news(self.data.news(list(self.cfg.universe),
                                                   self.cfg.ai["news_lookback_hours"]))
                    last_news = t
                errors = 0
            except Exception as e:
                errors += 1
                self.db.event("ERROR", "Fout in hoofdlus", repr(e))
                time.sleep(min(60 * errors, 900))  # oplopende wachttijd
            time.sleep(60)


def main():
    ap = argparse.ArgumentParser(prog="agent")
    ap.add_argument("cmd", choices=["status", "once", "tick", "run"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ignore-market-hours", action="store_true")
    a = ap.parse_args()
    if a.ignore_market_hours and not a.dry_run:
        raise SystemExit("--ignore-market-hours mag enkel samen met --dry-run")
    agent = Agent(config.load())
    if a.cmd == "status":
        agent.status()
    elif a.cmd == "tick":
        agent.tick(dry_run=a.dry_run)
    elif a.cmd == "once":
        agent.analyse_and_trade(dry_run=a.dry_run, ignore_hours=a.ignore_market_hours)
    else:
        agent.run_forever()


if __name__ == "__main__":
    main()
