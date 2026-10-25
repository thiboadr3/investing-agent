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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import ai, config, risk, rules, strategy
from .broker import Broker
from .data import MarketData
from .db import DB, now
from .notify import Notifier, esc
from .shadow import NAMES, Shadows

NY = ZoneInfo("America/New_York")
SESSION_MIN = 390  # reguliere sessie 9:30–16:00 ET


class _NoNotify:
    enabled = False

    def send(self, *a, **k):
        return False


class Agent:
    notify = _NoNotify()   # wordt in __init__ vervangen door een echte Notifier

    def __init__(self, cfg: config.Config):
        self.cfg = cfg
        self.db = DB(config.DB_PATH)
        self.broker = Broker(cfg.alpaca_key, cfg.alpaca_secret)
        self.data = MarketData(cfg.alpaca_key, cfg.alpaca_secret)
        self._analyst = None
        self.shadows = Shadows(self.db, cfg.shadows.get("cost_pct", {}))
        self.notify = Notifier(self.db)
        day = datetime.now(NY).strftime("%Y%m%d")
        self.db.on_error = lambda msg, detail: self.notify.send(
            f"⚠️ <b>Investing Agent – fout</b>\n{esc(msg)}\n<code>{esc(str(detail or '')[:300])}</code>",
            key=f"err_{day}_{abs(hash(msg)) % 10**8}")

    @property
    def analyst(self):
        if self._analyst is None:
            self._analyst = ai.Analyst(self.cfg.gemini_key, self.cfg.ai["model"],
                                       self.cfg.ai["temperature"],
                                       self.cfg.ai.get("fallback_models", []))
            self._analyst.before_call = self._ai_budget_check
        return self._analyst

    def _ai_budget_check(self):
        """Kostenrem vóór elke AI-poging: max geslaagde (betaalde) aanroepen per dag,
        max pogingen per dag (vangnet tegen lussen) en het maandbudget."""
        today = datetime.now(NY).strftime("%Y%m%d")
        ok = self.db.get(f"ai_ok_{today}", 0)
        n = self.db.get(f"ai_calls_{today}", 0)
        limit = self.cfg.ai.get("max_calls_per_day", 12)
        attempts = self.cfg.ai.get("max_attempts_per_day", 40)
        if ok >= limit:
            raise RuntimeError(f"Kostenrem: max {limit} geslaagde AI-aanroepen per dag bereikt")
        if n >= attempts:
            raise RuntimeError(f"Kostenrem: max {attempts} AI-pogingen per dag bereikt")
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
        # pauzeregel: bij >= max terugval geen aankopen; na `pause_days` kalenderdagen wordt de
        # piek gereset. Zonder reset blijft een portefeuille in cash voor altijd geblokkeerd.
        dd = risk.drawdown_pct(acct.equity, peak)
        pause = self.db.get("pause_since")
        today = datetime.now(NY).date()
        if pause:
            if (today - datetime.fromisoformat(pause).date()).days >= self.cfg.risk.pause_days:
                self.db.event("INFO", f"Pauze voorbij: piek gereset van ${peak:,.0f} "
                                      f"naar ${acct.equity:,.0f}")
                peak = acct.equity
                self.db.set("pause_since", None)
        elif dd >= self.cfg.risk.max_drawdown_pct:
            self.db.set("pause_since", today.isoformat())
            self.db.event("WARN", f"Terugval {dd:.1f}%: pauze voor nieuwe aankopen "
                                  f"({self.cfg.risk.pause_days} dagen)")
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
        okey = f"ai_ok_{datetime.now(NY).strftime('%Y%m%d')}"
        self.db.set(okey, self.db.get(okey, 0) + 1)
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
        done, refused = [], []
        try:
            self._execute_inner(props, ctx, cycle_id, dry_run, reason, r, done, refused)
        finally:
            if done or refused:
                head = "🧪 <b>Testrun (niets geplaatst)</b>" if dry_run else "✅ <b>Orders geplaatst (paper)</b>"
                lines = [head] + [f"{'🟢 koop' if s == 'buy' else '🔴 verkoop'} {esc(sym)} ${n:,.0f}"
                                  for s, sym, n in done]
                lines += [f"⛔ geweigerd {esc(sym)} ({esc(rule)})" for sym, rule in refused]
                self.notify.send("\n".join(lines))

    def _execute_inner(self, props, ctx, cycle_id, dry_run, reason, r, done, refused):
        for p in props:
            cid = f"ia-{cycle_id}-{p.symbol.replace('/', '')}-{p.side}"
            if self.db.order_exists(cid) or self.broker.order_by_client_id(cid):
                continue  # al uitgevoerd (bv. na herstart)
            rule = risk.check_order(p, ctx, r)
            if rule:
                self.db.x("INSERT INTO rejections VALUES (?,?,?,?,?,?)",
                          (now(), cycle_id, p.symbol, p.side, rule, f"${p.notional:,.0f}"))
                print(f"  geweigerd {p.side} {p.symbol} ${p.notional:,.0f}: {rule}")
                refused.append((p.symbol, rule))
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
            done.append((p.side, p.symbol, p.notional))
            ctx.orders_today += 0 if dry_run else 1
            ctx.open_order_symbols.add(p.symbol)
            if p.side == "buy":
                ctx.cash -= p.notional
                ctx.position_values[p.symbol] = ctx.position_values.get(p.symbol, 0) + p.notional

    def _rule_targets(self, snaps, held=None):
        r = self.cfg.risk
        return rules.targets(snaps, self.cfg.strategy, r.max_position_pct / 100,
                             r.max_crypto_total_pct / 100, r.max_crypto_position_pct / 100,
                             held, self.cfg.sectors, self.cfg.benchmark)

    # ---------- 1. onderzoek vóór de opening ----------
    def build_plan(self) -> dict:
        """Data + regels + AI-filter -> kooplijst voor vandaag. Plaatst zelf niets."""
        cfg = self.cfg
        cycle_id = datetime.now(NY).strftime("%Y%m%d")
        acct, pos, _ = self.snapshot()
        snaps = self.data.snapshots(list(cfg.universe), list(cfg.crypto),
                                    cfg.strategy.get("trend_sma_days", 200))
        news = self.data.news(list(cfg.universe), cfg.ai["news_lookback_hours"], 50)
        if cfg.crypto:
            news += self.data.news(list(cfg.crypto), cfg.ai["news_lookback_hours"], 20)
        self.store_news(news)

        if cfg.benchmark in snaps:
            self.db.set(f"spy_{cycle_id}", snaps[cfg.benchmark].price)
        rule_w, why = self._rule_targets(snaps, set(pos))   # regels bepalen wat en hoeveel
        final_w, ai_ok, notes, view, raw, fiches = dict(rule_w), True, [], "", None, {}
        if cfg.strategy.get("ai_filter", True) and rule_w:   # AI mag enkel verkleinen
            try:
                lessons = [x for (x,) in self.db.x(
                    "SELECT lesson FROM lessons ORDER BY ts DESC LIMIT 8").fetchall()]
                raw = self._ai_call(ai.filter_prompt(snaps, rule_w, news, lessons), "filter+debat")
                factors, cf, notes, view, fiches = ai.parse_filter(raw, set(rule_w))
                for s in final_w:
                    final_w[s] = round(final_w[s] * factors.get(s, 1.0)
                                       * (cf if config.is_crypto(s) else 1.0), 4)
                final_w = {s: w for s, w in final_w.items() if w > 0}
            except Exception as e:
                ai_ok = False
                self.db.event("ERROR", "AI-filter mislukt: vandaag enkel verkopen", str(e))

        ai_note = {n["symbol"]: n for n in notes}
        for s in sorted(set(rule_w) | set(final_w) | set(pos)):
            n = ai_note.get(s)
            action = "drop" if n and n["factor"] == 0 else "halve" if n else "keep"
            fi = fiches.get(s, {})
            self.db.x("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?)",
                      (now(), cycle_id, s, action, final_w.get(s, 0.0), None,
                       json.dumps([why.get(s, "")] + ([fi["bull"]] if fi.get("bull") else []),
                                  ensure_ascii=False),
                       json.dumps(([fi["bear"]] if fi.get("bear") else [])
                                  + ([n["reason"]] if n else []), ensure_ascii=False), raw))
        if view:
            self.db.event("INFO", f"AI-marktbeeld: {view[:300]}")

        # fiche per positie (wat doet het bedrijf, voor/tegen, risico) uit dezelfde AI-aanroep
        for s in final_w:
            f = dict(fiches.get(s, {}))
            f.update({"rule": why.get(s, ""), "ai_note": (ai_note.get(s) or {}).get("reason", ""),
                      "weight": final_w[s],
                      "metrics": {"momentum_12_1": snaps[s].mom_12_1, "ret_3m": snaps[s].ret_3m,
                                  "vol_3m": snaps[s].vol_3m, "price": snaps[s].price}
                      if s in snaps else {}})
            self.db.x("INSERT OR REPLACE INTO fiches VALUES (?,?,?)",
                      (s, cycle_id, json.dumps(f, ensure_ascii=False)))

        plan = {"cycle": cycle_id, "built": now(), "weights": final_w, "rule_weights": rule_w,
                "ai_ok": ai_ok, "free_weights": None,
                "why": {s: why.get(s, "") for s in final_w}}
        self.db.set(f"plan_{cycle_id}", plan)
        top = sorted(final_w.items(), key=lambda kv: -kv[1])
        self.db.event("INFO", f"Plan {cycle_id}: {len(final_w)} doelposities "
                              f"({sum(final_w.values()):.0%} belegd), AI-filter "
                              f"{'OK' if ai_ok else 'MISLUKT'}: "
                              + ", ".join(f"{s} {w:.1%}" for s, w in top))
        lines = [f"📋 <b>Plan {cycle_id[6:]}-{cycle_id[4:6]}</b> · {len(final_w)} posities, "
                 f"{sum(final_w.values()):.0%} belegd · AI-filter {'OK' if ai_ok else 'MISLUKT (vandaag enkel verkopen)'}",
                 ", ".join(f"{esc(s)} {w:.0%}" for s, w in top)]
        for n in notes:
            lines.append(f"✂️ {esc(n['symbol'])} {'geschrapt' if n['factor'] == 0 else 'gehalveerd'}: "
                         f"{esc(n['reason'][:200])}")
        self.notify.send("\n".join(lines), key=f"plan_{cycle_id}_{int(ai_ok)}")
        # schaduw 'AI vrij' NA het bewaren van het plan: mag het echte plan nooit tegenhouden
        free_w = None
        if cfg.shadows.get("enabled", True):
            try:
                cur = self.shadows._load("ai_vrij")
                prices = {s: v.price for s, v in snaps.items()}
                tot = self.shadows.value(cur, prices) if cur else 0
                cur_w = ({s: q * prices.get(s, 0) / tot for s, q in cur["h"].items()}
                         if cur and tot else {})
                max_w = cfg.shadows.get("ai_free_max_position_pct", 25) / 100
                raw_f = self._ai_call(ai.free_prompt(snaps, cur_w, news, max_w), "vrij")
                free_w, _ = ai.parse_free(raw_f, set(cfg.all_symbols), max_w)
            except Exception as e:
                self.db.event("WARN", "Schaduw 'AI vrij': geen beslissing vandaag", str(e))

        if free_w is not None:
            plan["free_weights"] = free_w
            self.db.set(f"plan_{cycle_id}", plan)
        return plan

    # ---------- 2. uitvoeren na de opening ----------
    def execute_plan(self, plan: dict, dry_run: bool, ignore_hours: bool = False):
        cfg, r = self.cfg, self.cfg.risk
        cycle_id = plan["cycle"]
        acct, pos, peak = self.snapshot()
        clock = self.broker.market_clock()
        # verse koersen voor de datacontrole en de schaduwportefeuilles
        snaps = self.data.snapshots(list(cfg.universe), list(cfg.crypto),
                                    cfg.strategy.get("trend_sma_days", 200))
        ctx = self._risk_ctx(acct, pos, peak, clock, snaps, dry_run, ignore_hours)
        props = strategy.proposals(plan["weights"], acct.equity, ctx.position_values,
                                   set(cfg.all_symbols), r.min_order_usd,
                                   allow_buys=plan["ai_ok"],
                                   band=cfg.strategy.get("rebalance_band_pct", 0) / 100)
        self.db.event("INFO", f"Uitvoering {cycle_id}: {len(props)} orderkandidaten "
                              f"(plan van {plan['built']})")
        self._execute(props, ctx, cycle_id, dry_run, "regels+ai" if plan["ai_ok"] else "regels")
        self.db.set("last_analysis_dry" if dry_run else "last_analysis", cycle_id)
        if cfg.shadows.get("enabled", True):
            self.update_shadows(snaps, plan, acct.equity, cycle_id)

    def analyse_and_trade(self, dry_run: bool, ignore_hours: bool = False):
        """Handmatig: onderzoek + uitvoering in één keer."""
        self.execute_plan(self.build_plan(), dry_run, ignore_hours)

    def update_shadows(self, snaps, plan, equity, cycle_id):
        if self.db.get("last_shadow_day") == cycle_id:
            return
        prices = {s: v.price for s, v in snaps.items()}
        sh = self.shadows
        names = [n for n in NAMES if n != "50_50" or self.cfg.crypto]
        for name in names:
            sh.ensure(name, equity)
        sh.rebalance("regels_zonder_ai", plan["rule_weights"], prices)
        if self.cfg.crypto:
            sh.rebalance("50_50", rules.fixed_split(snaps, self.cfg.strategy, 0.5,
                                                    self.cfg.risk.max_position_pct / 100), prices)
        if not sh._load("spy")["h"]:
            sh.rebalance("spy", {self.cfg.benchmark: 1.0}, prices)
        if plan.get("free_weights") is not None:
            sh.rebalance("ai_vrij", plan["free_weights"], prices)
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
        """Eén korte doorloop, bedoeld voor een planner (GitHub Actions/cron).

        Vóór de opening: onderzoek -> plan. Na de opening: plan meteen uitvoeren.
        """
        sch = self.cfg.schedule
        clock = self.broker.market_clock()
        _, pos, _ = self.snapshot() or (None, {}, None)
        self.reconcile()
        try:
            self.update_journal(pos)
        except Exception as e:
            self.db.event("WARN", "Dagboek niet bijgewerkt", str(e))
        today = datetime.now(NY).strftime("%Y%m%d")
        plan = self.db.get(f"plan_{today}")
        done = self.db.get("last_analysis_dry" if dry_run else "last_analysis") == today
        if clock.is_open:
            mins_open = SESSION_MIN - (clock.next_close - clock.timestamp).total_seconds() / 60
            if done:
                print("Plan van vandaag is al uitgevoerd; enkel opvolging.")
            elif mins_open < sch.get("execute_after_open_min", 5):
                print(f"Beurs net open ({mins_open:.0f} min); uitvoering bij volgende run.")
            else:
                if plan is None or (not plan["ai_ok"] and not plan.get("retried")):
                    if plan is not None:
                        print("AI-filter faalde vóór de opening; nog één poging.")
                    plan = self.build_plan()
                    plan["retried"] = True
                    self.db.set(f"plan_{today}", plan)
                self.execute_plan(plan, dry_run)
        else:
            until_open = (clock.next_open - clock.timestamp).total_seconds() / 3600
            opens_today = clock.next_open.astimezone(NY).strftime("%Y%m%d") == today
            if opens_today and until_open <= sch.get("premarket_hours", 3) and plan is None:
                print(f"Beurs opent over {until_open:.1f} u: onderzoek en plan maken.")
                self.build_plan()
            elif plan is not None and not done:
                print("Plan klaar; wordt uitgevoerd na de opening.")
            else:
                print(f"Beurs gesloten (volgende opening {clock.next_open}).")
            self.crypto_exit_check(dry_run)
            try:
                self.daily_close_note(clock)
            except Exception as e:
                self.db.event("WARN", "Dagafsluiting niet verstuurd", str(e))
            self.weekly_review()
        self.report()
        try:
            self.portfolio_overview()
        except Exception as e:
            self.db.event("WARN", "Portefeuilleoverzicht niet gemaakt", str(e))

    # ---------- geheugen: tradedagboek ----------
    def update_journal(self, pos: dict):
        """Houdt open posities bij; bij een volledige verkoop komt er een dagboekregel."""
        today = datetime.now(NY).strftime("%Y-%m-%d")
        open_pos = self.db.get("open_positions", {}) or {}
        for s in pos:
            if s not in open_pos:
                f = self.db.x("SELECT data FROM fiches WHERE symbol=? ORDER BY day DESC LIMIT 1",
                              (s,)).fetchone()
                open_pos[s] = {"opened": today,
                               "reason": (json.loads(f[0]).get("rule", "") if f else "")}
        for s in [s for s in open_pos if s not in pos]:
            o = open_pos.pop(s)
            q = lambda side: self.db.x(
                "SELECT COALESCE(SUM(notional),0) FROM orders WHERE symbol=? AND side=? AND "
                "status NOT IN ('dry_run','canceled','rejected','expired') AND ts >= ?",
                (s, side, o["opened"])).fetchone()[0]
            buy, sell = q("buy"), q("sell")
            ex = self.db.x("SELECT reasons_for, action FROM decisions WHERE symbol=? "
                           "ORDER BY ts DESC LIMIT 1", (s,)).fetchone()
            exit_reason = (("AI: " + ex[1] + " · ") if ex and ex[1] != "keep" else "") + \
                          (json.loads(ex[0])[0] if ex and ex[0] else "")
            spy0 = self.db.get(f"spy_{o['opened'].replace('-', '')}")
            spy1 = self.db.get(f"spy_{today.replace('-', '')}")
            spy_pct = (spy1 / spy0 - 1) if spy0 and spy1 else None
            days = (datetime.fromisoformat(today) - datetime.fromisoformat(o["opened"])).days
            self.db.x("INSERT INTO journal VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (s, o["opened"], today, buy, sell, sell - buy,
                       (sell / buy - 1) if buy else None, days, o.get("reason", ""),
                       exit_reason, spy_pct))
            self.db.event("INFO", f"Dagboek: {s} gesloten na {days} d, "
                                  f"resultaat ${sell - buy:+,.0f}")
        self.db.set("open_positions", open_pos)

    # ---------- geheugen: wekelijkse evaluatie ----------
    def weekly_review(self, force: bool = False, path="reports/WEEKLY.md"):
        nyt = datetime.now(NY)
        # de evaluatie hoort bij de laatste afgesloten vrijdag; wordt ze gemist (geen run na
        # de sluiting), dan haalt de eerstvolgende run (weekend of maandag-donderdag) ze in
        wd = nyt.weekday()
        if wd == 4 and (nyt.hour, nyt.minute) >= (16, 15):
            friday = nyt.date()
        elif wd >= 5:
            friday = nyt.date() - timedelta(days=wd - 4)
        else:
            friday = nyt.date() - timedelta(days=wd + 3)
        week = friday.strftime("%G-W%V")
        if not force and self.db.get("last_review") == week:
            return
        acct, pos, peak = self.snapshot()
        jr = self.db.x("SELECT symbol, opened, closed, pnl, pnl_pct, days, entry_reason, "
                       "exit_reason, spy_pct FROM journal ORDER BY closed DESC LIMIT 25").fetchall()
        lines = [f"Datum: {nyt:%Y-%m-%d}. Portefeuille ${acct.equity:,.0f} (cash ${acct.cash:,.0f}), "
                 f"terugval vanaf piek {risk.drawdown_pct(acct.equity, peak):.1f}%.", "",
                 "OPEN POSITIES (symbool | waarde | resultaat sinds aankoop):"]
        lines += [f"{p.symbol} | ${p.market_value:,.0f} | {p.unrealized_plpc:+.1%}"
                  for p in sorted(pos.values(), key=lambda p: -p.market_value)]
        lines += ["", "AFGESLOTEN TRADES (symbool | open | dicht | resultaat | dagen | instap | uitstap | SPY zelfde periode):"]
        lines += [f"{r[0]} | {r[1]} | {r[2]} | ${r[3]:+,.0f} ({'' if r[4] is None else f'{r[4]:+.1%}'}) | "
                  f"{r[5]} | {r[6]} | {r[7]} | {'' if r[8] is None else f'{r[8]:+.1%}'}" for r in jr] or ["(nog geen)"]
        lines += ["", "AI-AANPASSINGEN (laatste 30): " + ", ".join(
            f"{s} {a}" for s, a in self.db.x("SELECT symbol, action FROM decisions WHERE action != "
                                             "'keep' ORDER BY ts DESC LIMIT 30").fetchall()) or "geen"]
        rej = self.db.x("SELECT rule, COUNT(*) FROM rejections GROUP BY rule").fetchall()
        lines += ["", "GEWEIGERDE ORDERS: " + (", ".join(f"{r} ×{n}" for r, n in rej) or "geen"), "",
                  "SCHADUWPORTEFEUILLES:"]
        lines += [f"{x['label']}: {x['return']:+.2%} (max daling {x['max_drawdown']:.1%})"
                  for x in self.shadows.summary()]
        facts = "\n".join(lines)
        try:
            rv = ai.parse_review(self._ai_call(ai.review_prompt(facts), "weekevaluatie"))
        except Exception as e:
            self.db.event("WARN", "Weekevaluatie mislukt", str(e))
            return
        for les in rv["lessons"]:
            self.db.x("INSERT INTO lessons VALUES (?,?,?)", (now(), week, les))
        self.db.set("last_review", week)
        self.db.set(f"review_{week}", rv)
        md = [f"## Week {week} ({nyt:%d-%m-%Y})", "", rv["summary"], "", "**Lessen** (gaan als context naar de AI-filter):"]
        md += [f"- {x}" for x in rv["lessons"]] + ["", "**Hypotheses om te backtesten** (niet automatisch doorgevoerd):"]
        md += [f"- {x}" for x in rv["hypotheses"]] + [""]
        out = config.ROOT / path
        out.parent.mkdir(parents=True, exist_ok=True)
        prev = out.read_text().split("\n", 2)[2] if out.exists() else ""
        out.write_text("# Investing Agent — weekevaluaties\n\n" + "\n".join(md) + "\n" + prev)
        self.db.event("INFO", f"Weekevaluatie {week}: {len(rv['lessons'])} lessen")
        self.notify.send(f"🗓 <b>Weekevaluatie {week}</b>\n{esc(rv['summary'][:1200])}\n\n<b>Lessen</b>\n"
                         + "\n".join(f"• {esc(x)}" for x in rv["lessons"])
                         + "\n\nhttps://github.com/thiboadr3/investing-agent/blob/state/WEEKLY.md",
                         key=f"review_{week}")

    def portfolio_overview(self, path="reports/PORTFOLIO.md"):
        """Leesbaar overzicht per positie: wat, waarom, risico, resultaat, nieuws, links."""
        acct, pos, peak = self.snapshot()
        lines = ["# Investing Agent — portefeuille (paper)", "",
                 f"_Bijgewerkt {datetime.now(NY):%Y-%m-%d %H:%M} New York-tijd. Paperrekening, "
                 f"geen echt geld. Geen beleggingsadvies._", "",
                 f"**Waarde:** ${acct.equity:,.2f} · **cash:** ${acct.cash:,.2f} · "
                 f"**terugval vanaf piek:** {risk.drawdown_pct(acct.equity, peak):.1f}%", ""]
        stocks = sorted(pos.values(), key=lambda p: -p.market_value)
        if not stocks:
            lines += ["_Nog geen posities._", ""]
        else:
            lines += ["| Symbool | Bedrijf | Gewicht | Waarde | Aankoopprijs | Resultaat |",
                      "|---|---|---:|---:|---:|---:|"]
        details = []
        for p in stocks:
            row = self.db.x("SELECT data, day FROM fiches WHERE symbol=? ORDER BY day DESC LIMIT 1",
                            (p.symbol,)).fetchone()
            f = json.loads(row[0]) if row else {}
            name = f.get("company") or self.db.get(f"name_{p.symbol}")
            if not name:
                name = self.broker.asset_name(p.symbol)
                self.db.set(f"name_{p.symbol}", name)
            first = self.db.x("SELECT MIN(ts) FROM orders WHERE symbol=? AND side='buy' "
                              "AND status != 'dry_run'", (p.symbol,)).fetchone()[0]
            lines.append(f"| [{p.symbol}](#{p.symbol.lower().replace('.', '')}) | {name} | "
                         f"{p.market_value / acct.equity:.1%} | ${p.market_value:,.0f} | "
                         f"${p.avg_entry_price:,.2f} | {p.unrealized_plpc:+.1%} "
                         f"(${p.unrealized_pl:+,.0f}) |")
            m = f.get("metrics", {})
            news = self.db.x("SELECT created_at, headline, url FROM news WHERE ','||symbols||',' "
                             "LIKE ? ORDER BY created_at DESC LIMIT 3",
                             (f"%,{p.symbol},%",)).fetchall()
            sym = p.symbol
            d = [f"### {sym}", f"**{name}**" + (f" — gekocht sinds {first[:10]}" if first else ""), ""]
            if f.get("what"):
                d.append(f"- **Wat:** {f['what']}")
            d.append(f"- **Waarom gekozen (regels):** {f.get('rule') or '—'}")
            if f.get("bull") or f.get("why"):
                d.append(f"- **Argument voor:** {f.get('bull') or f.get('why')}")
            if f.get("bear"):
                d.append(f"- **Argument tegen:** {f['bear']}")
            if m:
                fmt = lambda v: "n/a" if v is None else f"{v:+.0%}"
                vol = m.get("vol_3m")
                vol_s = "n/a" if vol is None else f"{vol:.0%}"
                d.append(f"- **Cijfers bij aankoop:** momentum 12-1m {fmt(m.get('momentum_12_1'))}, "
                         f"3m {fmt(m.get('ret_3m'))}, volatiliteit {vol_s}")
            if f.get("risk"):
                d.append(f"- **Risico om op te volgen:** {f['risk']}")
            if f.get("ai_note"):
                d.append(f"- **AI-filter:** {f['ai_note']}")
            if news:
                d.append("- **Recent nieuws:** " + " · ".join(
                    f"[{h[:80]}]({u})" for _, h, u in news if h))
            d.append(f"- **Zelf verdiepen:** [Yahoo Finance](https://finance.yahoo.com/quote/{sym.replace('.', '-')}) · "
                     f"[SEC-rapporten](https://www.sec.gov/edgar/search/#/entityName={sym}) · "
                     f"[Finviz](https://finviz.com/quote.ashx?t={sym.replace('.', '-')})")
            details += d + [""]
        trades = self.db.x("SELECT ts, side, symbol, notional, status, reason FROM orders "
                           "WHERE status != 'dry_run' ORDER BY ts DESC LIMIT 20").fetchall()
        lines += ["", "## Details per positie", ""] + details
        lines += ["## Laatste orders", "", "| Tijd (UTC) | Actie | Symbool | Bedrag | Status | Reden |",
                  "|---|---|---|---:|---|---|"]
        for ts, side, s, n, st, rs in trades:
            lines.append(f"| {ts[:16]} | {'koop' if side == 'buy' else 'verkoop'} | {s} | "
                         f"${n:,.0f} | {st} | {rs} |")
        out = config.ROOT / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n")
        return out

    def daily_close_note(self, clock):
        """Eén korte dagsamenvatting na de sluiting (eerste run na 16:00 New York)."""
        nyt = datetime.now(NY)
        today = nyt.strftime("%Y%m%d")
        if clock.is_open or nyt.weekday() >= 5 or nyt.hour < 16 or not self.notify.enabled:
            return
        if self.db.get("last_analysis") != today and self.db.get("last_analysis_dry") != today:
            return   # geen handelsdag voor de agent (bv. feestdag)
        acct = self.broker.account()
        pos = self.broker.positions()
        first = self.db.x("SELECT equity FROM snapshots ORDER BY ts LIMIT 1").fetchone()
        start = first[0] if first else acct.equity
        day = acct.equity / acct.last_equity - 1 if acct.last_equity else 0
        movers = sorted(pos.values(), key=lambda p: p.unrealized_plpc)
        lines = [f"📊 <b>Dagafsluiting {nyt:%d-%m}</b>",
                 f"Waarde ${acct.equity:,.0f} · vandaag {day:+.2%} · totaal {acct.equity / start - 1:+.2%}"]
        if movers:
            best, worst = movers[-1], movers[0]
            lines.append(f"Beste: {esc(best.symbol)} {best.unrealized_plpc:+.1%} · "
                         f"zwakste: {esc(worst.symbol)} {worst.unrealized_plpc:+.1%} (sinds aankoop)")
        lines.append("https://github.com/thiboadr3/investing-agent/blob/state/PORTFOLIO.md")
        self.notify.send("\n".join(lines), key=f"close_{today}")

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
    ap.add_argument("cmd", choices=["status", "once", "tick", "report", "overview", "review",
                                    "notify-test", "run"])
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
    elif a.cmd == "notify-test":
        ok = agent.notify.send("👋 <b>Investing Agent</b> is verbonden met Telegram. "
                               "Je krijgt hier plannen, orders, fouten en weekevaluaties.")
        print("Telegram:", "verstuurd" if ok else "NIET verstuurd (token/chat ontbreekt?)")
    elif a.cmd == "review":
        agent.weekly_review(force=True)
    elif a.cmd == "overview":
        print(f"Geschreven: {agent.portfolio_overview()}")
    elif a.cmd == "tick":
        agent.tick(dry_run=a.dry_run)
    elif a.cmd == "once":
        agent.analyse_and_trade(dry_run=a.dry_run, ignore_hours=a.ignore_market_hours)
    else:
        agent.run_forever()


if __name__ == "__main__":
    main()
