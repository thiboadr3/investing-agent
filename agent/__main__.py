"""Investing Agent — paper trading.

Gebruik:
  python -m agent status                 rekening, posities, terugval
  python -m agent once --dry-run         één analyse, orders enkel loggen
  python -m agent once --dry-run --ignore-market-hours   idem, ook als beurs dicht is
  python -m agent once                   één analyse en echte PAPER-orders
  python -m agent tick [--dry-run]       één korte doorloop (voor GitHub Actions)
  python -m agent report                 echte portefeuille vs schaduwportefeuilles
  python -m agent run                    doorlopend (voor een eigen server)

Noodstop: maak een leeg bestand 'STOP' in de projectmap. Verwijder het om te hervatten.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import ai, config, risk, rules, strategy
from .broker import Broker
from .data import MarketData
from .db import DB, now
from .shadow import NAMES, Shadows

NY = ZoneInfo("America/New_York")
SESSION_MIN = 390  # reguliere sessie 9:30–16:00 ET


class Agent:
    def __init__(self, cfg: config.Config):
        self.cfg = cfg
        self.db = DB(config.DB_PATH)
        self.broker = Broker(cfg.alpaca_key, cfg.alpaca_secret)
        self.data = MarketData(cfg.alpaca_key, cfg.alpaca_secret)
        self._analyst = None
        self.shadows = Shadows(self.db, cfg.shadows.get("cost_pct", {}))

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

    # ---------- AI ----------
    def _ai_call(self, prompt: str, label: str) -> str:
        raw = self.analyst.analyse(prompt)
        u = self.analyst.last_usage
        cost = self._ai_cost(u)
        self.db.set("ai_cost_total_usd", round(self.db.get("ai_cost_total_usd", 0) + cost, 4))
        mkey = f"ai_cost_{datetime.now(NY).strftime('%Y%m')}"
        self.db.set(mkey, round(self.db.get(mkey, 0) + cost, 4))
        self.db.event("INFO", f"AI {label} ({self.analyst.last_model}): {u['input']} in / "
                              f"{u['output']} uit tokens ≈ ${cost:.4f}", u)
        return raw

    # ---------- analyse + handel ----------
    def _risk_ctx(self, acct, pos, peak, clock, snaps, dry_run, ignore_hours):
        return risk.Context(
            equity=acct.equity, cash=acct.cash, peak_equity=peak,
            position_values={s: p.market_value for s, p in pos.items()},
            position_qty={s: p.qty for s, p in pos.items()},
            open_order_symbols=self.broker.open_order_symbols(),
            universe=set(self.cfg.all_symbols), orders_today=self.db.orders_today(),
            market_open=bool(clock.is_open) or (dry_run and ignore_hours),
            account_ok=(not acct.trading_blocked and acct.status.endswith("ACTIVE")),
            stop_file=config.STOP_FILE.exists(),
            price_as_of={s: v.as_of for s, v in snaps.items()})

    def _execute(self, props, ctx, cycle_id: str, dry_run: bool, reason: str):
        r = self.cfg.risk
        for p in props:
            cid = f"ia-{cycle_id}-{p.symbol.replace('/', '')}-{p.side}"
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
                         if full_exit else
                         self.broker.submit(p.symbol, p.side, cid, notional=p.notional))
                    status, broker_id = "submitted", str(o.id)
                except Exception as e:
                    self.db.event("ERROR", f"Order {cid} mislukt", str(e))
                    continue
            self.db.x("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)",
                      (now(), cid, p.symbol, p.side, p.notional, None, status, broker_id, reason))
            print(f"  {status}: {p.side} {p.symbol} ${p.notional:,.0f}")
            ctx.orders_today += 0 if dry_run else 1
            ctx.open_order_symbols.add(p.symbol)
            if p.side == "buy":
                ctx.cash -= p.notional
                ctx.position_values[p.symbol] = ctx.position_values.get(p.symbol, 0) + p.notional

    def _rule_targets(self, snaps):
        r = self.cfg.risk
        return rules.targets(snaps, self.cfg.strategy, r.max_position_pct / 100,
                             r.max_crypto_total_pct / 100, r.max_crypto_position_pct / 100)

    def analyse_and_trade(self, dry_run: bool, ignore_hours: bool = False):
        cfg, r = self.cfg, self.cfg.risk
        cycle_id = datetime.now(NY).strftime("%Y%m%d")  # één analyse per beursdag
        acct, pos, peak = self.snapshot()
        clock = self.broker.market_clock()

        snaps = self.data.snapshots(list(cfg.universe), list(cfg.crypto),
                                    cfg.strategy.get("trend_sma_days", 200))
        news = (self.data.news(list(cfg.universe), cfg.ai["news_lookback_hours"], 50)
                + self.data.news(list(cfg.crypto), cfg.ai["news_lookback_hours"], 20))
        self.store_news(news)

        # 1) regels bepalen de doelportefeuille
        rule_w, why = self._rule_targets(snaps)

        # 2) AI mag enkel verkleinen
        final_w, ai_ok, notes, view, raw = dict(rule_w), True, [], "", None
        if cfg.strategy.get("ai_filter", True) and rule_w:
            try:
                raw = self._ai_call(ai.filter_prompt(snaps, rule_w, news), "filter")
                factors, cf, notes, view = ai.parse_filter(raw, set(rule_w))
                for s in final_w:
                    final_w[s] = round(final_w[s] * factors.get(s, 1.0)
                                       * (cf if config.is_crypto(s) else 1.0), 4)
                final_w = {s: w for s, w in final_w.items() if w > 0}
            except Exception as e:
                ai_ok = False
                self.db.event("ERROR", "AI-filter mislukt: enkel verkopen, geen aankopen", str(e))

        ai_note = {n["symbol"]: n for n in notes}
        for s in sorted(set(rule_w) | set(final_w) | {p for p in pos}):
            n = ai_note.get(s)
            action = "drop" if n and n["factor"] == 0 else "halve" if n else "keep"
            self.db.x("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?)",
                      (now(), cycle_id, s, action, final_w.get(s, 0.0), None,
                       json.dumps([why.get(s, "")], ensure_ascii=False),
                       json.dumps([n["reason"]] if n else [], ensure_ascii=False), raw))
        if view:
            self.db.event("INFO", f"AI-marktbeeld: {view[:300]}")

        # 3) orders
        ctx = self._risk_ctx(acct, pos, peak, clock, snaps, dry_run, ignore_hours)
        props = strategy.proposals(final_w, acct.equity, ctx.position_values,
                                   set(cfg.all_symbols), r.min_order_usd, allow_buys=ai_ok)
        crypto_w = sum(w for s, w in final_w.items() if config.is_crypto(s))
        self.db.event("INFO", f"Cyclus {cycle_id}: {len(final_w)} doelposities "
                              f"(crypto {crypto_w:.0%}), {len(props)} orderkandidaten")
        self._execute(props, ctx, cycle_id, dry_run, "regels+ai" if ai_ok else "regels")
        self.db.set("last_analysis_dry" if dry_run else "last_analysis", cycle_id)

        # 4) schaduwportefeuilles
        if cfg.shadows.get("enabled", True):
            self.update_shadows(snaps, news, rule_w, acct.equity, cycle_id)

    def update_shadows(self, snaps, news, rule_w, equity, cycle_id):
        if self.db.get("last_shadow_day") == cycle_id:
            return
        prices = {s: v.price for s, v in snaps.items()}
        sh, strat = self.shadows, self.cfg.strategy
        for name in NAMES:
            sh.ensure(name, equity)
        sh.rebalance("regels_zonder_ai", rule_w, prices)
        sh.rebalance("50_50", rules.fixed_split(snaps, strat, 0.5,
                                                self.cfg.risk.max_position_pct / 100), prices)
        if not sh._load("spy")["h"]:
            sh.rebalance("spy", {self.cfg.benchmark: 1.0}, prices)
        try:
            cur = sh._load("ai_vrij")
            tot = sh.value(cur, prices)
            cur_w = {s: q * prices.get(s, 0) / tot for s, q in cur["h"].items()} if tot else {}
            max_w = self.cfg.shadows.get("ai_free_max_position_pct", 25) / 100
            raw = self._ai_call(ai.free_prompt(snaps, cur_w, news, max_w), "vrij")
            free_w, _ = ai.parse_free(raw, set(self.cfg.all_symbols), max_w)
            sh.rebalance("ai_vrij", free_w, prices)
        except Exception as e:
            self.db.event("WARN", "Schaduw 'AI vrij' niet bijgewerkt", str(e))
        sh.mark(prices)
        self.db.set("last_shadow_day", cycle_id)

    def crypto_exit_check(self, dry_run: bool):
        """Buiten beursuren: verkoop crypto waarvan de trend gebroken is. Nooit kopen."""
        if not self.cfg.crypto:
            return
        acct, pos, peak = self.snapshot()
        held = [s for s in pos if config.is_crypto(s)]
        if not held:
            print("Geen crypto in portefeuille; niets te controleren.")
            return
        snaps = self.data.snapshots([], list(self.cfg.crypto),
                                    self.cfg.strategy.get("trend_sma_days", 200))
        r = self.cfg.risk
        cw, why = rules.crypto_targets(snaps, r.max_crypto_total_pct / 100,
                                       r.max_crypto_position_pct / 100)
        exits = {s: 0.0 for s in held if cw.get(s, 0) == 0}
        if not exits:
            print("Crypto-trend intact; geen actie.")
            return
        keep = {s: pos[s].market_value / acct.equity for s in pos if s not in exits}
        ctx = self._risk_ctx(acct, pos, peak, self.broker.market_clock(), snaps, dry_run, False)
        props = strategy.proposals(keep, acct.equity, ctx.position_values,
                                   set(exits), r.min_order_usd, allow_buys=False)
        cycle = datetime.now(NY).strftime("%Y%m%d") + "x"
        for s in exits:
            self.db.event("INFO", f"Crypto-uitstap {s}: {why.get(s, '')}")
        self._execute(props, ctx, cycle, dry_run, "crypto-uitstap")

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
        self.snapshot()
        self.reconcile()
        if not clock.is_open:
            print(f"Beurs gesloten (volgende opening {clock.next_open}); crypto-controle.")
            self.crypto_exit_check(dry_run)
        else:
            mins_left = (clock.next_close - clock.timestamp).total_seconds() / 60
            today = datetime.now(NY).strftime("%Y%m%d")
            key = "last_analysis_dry" if dry_run else "last_analysis"
            if self.db.get(key) == today:
                print("Analyse van vandaag is al gebeurd; enkel opvolging.")
            elif mins_left > SESSION_MIN - self.cfg.schedule["analysis_after_open_min"]:
                print("Te vroeg na de opening; analyse volgt bij een volgende run.")
            else:
                self.analyse_and_trade(dry_run=dry_run)
        self.report()

    def report(self):
        rows = self.db.x("SELECT equity FROM snapshots ORDER BY ts").fetchall()
        real = None
        if rows:
            start, last, pk, mdd = rows[0][0], rows[-1][0], rows[0][0], 0.0
            for (v,) in rows:
                pk = max(pk, v)
                mdd = max(mdd, (pk - v) / pk if pk else 0)
            rate = self.cfg.shadows.get("cost_pct", {})
            est = sum(n * (rate.get("crypto", 0.25) if "/" in s else rate.get("stock", 0.05)) / 100
                      for s, n in self.db.x("SELECT symbol, notional FROM orders "
                                            "WHERE status != 'dry_run'").fetchall())
            real = {"label": "ECHT (paper): regels + AI-filter", "start": start, "value": last,
                    "return": last / start - 1, "max_drawdown": mdd, "costs": est}
        table = ([real] if real else []) + self.shadows.summary()
        month = datetime.now(NY).strftime("%Y%m")
        lines = ["| Portefeuille | Start | Nu | Rendement | Max. terugval | Kosten (geschat) |",
                 "|---|---:|---:|---:|---:|---:|"]
        for x in table:
            lines.append(f"| {x['label']} | ${x['start']:,.0f} | ${x['value']:,.0f} | "
                         f"{x['return']:+.2%} | {x['max_drawdown']:.1%} | ${x['costs']:,.2f} |")
        lines.append(f"\nAI-kosten deze maand: ${self.db.get(f'ai_cost_{month}', 0):.2f} "
                     f"(max ${self.cfg.ai.get('max_cost_per_month_usd', 5)})")
        if self.db.get("last_shadow_day") is None:
            lines.append("\nSchaduwportefeuilles starten bij de eerste dagelijkse analyse.")
        md = "\n".join(lines)
        print(md)
        summary = os.getenv("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a") as f:
                f.write("## Investing Agent\n\n" + md + "\n")

    def run_forever(self):
        self.db.event("INFO", "Agent gestart (paper)")
        errors = 0
        while True:
            try:
                self.tick(dry_run=False)
                errors = 0
            except Exception as e:
                errors += 1
                self.db.event("ERROR", "Fout in hoofdlus", repr(e))
            time.sleep(min(self.cfg.schedule["check_interval_min"] * 60 * (1 + errors), 3600))


def main():
    ap = argparse.ArgumentParser(prog="agent")
    ap.add_argument("cmd", choices=["status", "once", "tick", "report", "run"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ignore-market-hours", action="store_true")
    a = ap.parse_args()
    if a.ignore_market_hours and not a.dry_run:
        raise SystemExit("--ignore-market-hours mag enkel samen met --dry-run")
    agent = Agent(config.load())
    if a.cmd == "status":
        agent.status()
    elif a.cmd == "report":
        agent.report()
    elif a.cmd == "tick":
        agent.tick(dry_run=a.dry_run)
    elif a.cmd == "once":
        agent.analyse_and_trade(dry_run=a.dry_run, ignore_hours=a.ignore_market_hours)
    else:
        agent.run_forever()


if __name__ == "__main__":
    main()
