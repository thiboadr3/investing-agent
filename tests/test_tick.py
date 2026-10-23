"""Dagplanning: onderzoek vóór de opening, uitvoering na de opening (gesimuleerde klok)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from agent import __main__ as m
from agent import config
from agent.db import DB


def make_agent(tmp_path, clock):
    a = m.Agent.__new__(m.Agent)
    a.cfg = config.load()
    a.db = DB(tmp_path / "t.db")
    a.calls = []
    a.broker = SimpleNamespace(market_clock=lambda: clock)
    a.snapshot = lambda: None
    a.reconcile = lambda: None
    a.report = lambda: None
    a.crypto_exit_check = lambda dry_run: None

    def build_plan():
        a.calls.append("plan")
        p = {"cycle": datetime.now(m.NY).strftime("%Y%m%d"), "ai_ok": True, "built": "x"}
        a.db.set(f"plan_{p['cycle']}", p)
        return p

    def execute_plan(plan, dry_run, ignore_hours=False):
        a.calls.append("exec")
        a.db.set("last_analysis_dry" if dry_run else "last_analysis", plan["cycle"])
    a.build_plan, a.execute_plan = build_plan, execute_plan
    return a


def clock(is_open, now, next_open=None, next_close=None):
    return SimpleNamespace(is_open=is_open, timestamp=now, next_open=next_open,
                           next_close=next_close)


def test_premarket_plan_then_execute_once(tmp_path):
    now = datetime.now(timezone.utc)
    # 2 uur voor opening -> plan maken, niets uitvoeren
    a = make_agent(tmp_path, clock(False, now, next_open=now + timedelta(hours=2)))
    a.tick(dry_run=True)
    assert a.calls == ["plan"]
    a.tick(dry_run=True)                       # tweede run vóór opening: geen nieuw plan
    assert a.calls == ["plan"]
    # 10 minuten na opening -> bestaand plan uitvoeren (geen nieuw onderzoek)
    a.broker = SimpleNamespace(market_clock=lambda: clock(
        True, now, next_close=now + timedelta(minutes=m.SESSION_MIN - 10)))
    a.tick(dry_run=True)
    assert a.calls == ["plan", "exec"]
    a.tick(dry_run=True)                       # daarna enkel opvolging
    assert a.calls == ["plan", "exec"]


def test_too_early_after_open_waits(tmp_path):
    now = datetime.now(timezone.utc)
    a = make_agent(tmp_path, clock(True, now, next_close=now + timedelta(minutes=m.SESSION_MIN - 2)))
    a.tick(dry_run=True)
    assert a.calls == []


def test_missed_premarket_plans_at_open(tmp_path):
    now = datetime.now(timezone.utc)
    a = make_agent(tmp_path, clock(True, now, next_close=now + timedelta(minutes=200)))
    a.tick(dry_run=True)
    assert a.calls == ["plan", "exec"]


def test_far_from_open_does_nothing(tmp_path):
    now = datetime.now(timezone.utc)
    a = make_agent(tmp_path, clock(False, now, next_open=now + timedelta(hours=20)))
    a.tick(dry_run=True)
    assert a.calls == []
