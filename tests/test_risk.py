from datetime import datetime, timedelta, timezone

from agent import ai, strategy
from agent.config import Risk
from agent.risk import Context, Proposal, check_order

NOW = datetime(2026, 10, 22, 15, tzinfo=timezone.utc)
R = Risk(max_drawdown_pct=15, max_position_pct=10, min_cash_pct=5, max_orders_per_day=10,
         min_order_usd=100, min_ai_confidence=0.6, max_data_age_hours=96)


def ctx(**kw):
    base = dict(equity=10_000, cash=10_000, peak_equity=10_000, position_values={},
                position_qty={}, open_order_symbols=set(), universe={"AAPL", "SPY"},
                orders_today=0, market_open=True, account_ok=True, stop_file=False,
                price_as_of={"AAPL": NOW - timedelta(hours=1), "SPY": NOW})
    base.update(kw)
    return Context(**base)


def chk(p, **kw):
    return check_order(p, ctx(**kw), R, now=NOW)


def test_ok_buy():
    assert chk(Proposal("AAPL", "buy", 900, 0.8)) is None


def test_position_limit():
    assert chk(Proposal("AAPL", "buy", 1500, 0.8)) == "max_positiegrootte"


def test_drawdown_blocks_buys_not_sells():
    kw = dict(equity=8_400, peak_equity=10_000, position_values={"AAPL": 500},
              position_qty={"AAPL": 2})
    assert chk(Proposal("SPY", "buy", 500, 0.9), **kw) == "max_terugval_bereikt"
    assert chk(Proposal("AAPL", "sell", 500, 0.9), **kw) is None


def test_no_shorts():
    assert chk(Proposal("AAPL", "sell", 500, 0.9)) == "geen_positie_om_te_verkopen"


def test_misc_rules():
    assert chk(Proposal("TSLA", "buy", 500, 0.9)) == "niet_in_universum"
    assert chk(Proposal("AAPL", "buy", 500, 0.9), stop_file=True) == "noodstop_actief"
    assert chk(Proposal("AAPL", "buy", 500, 0.9), market_open=False) == "markt_gesloten"
    assert chk(Proposal("AAPL", "buy", 500, 0.5)) == "te_lage_zekerheid"
    assert chk(Proposal("AAPL", "buy", 500, 0.9), cash=600) == "cashbuffer"
    assert chk(Proposal("AAPL", "buy", 500, 0.9), open_order_symbols={"AAPL"}) == "open_order_bestaat_al"
    assert chk(Proposal("AAPL", "buy", 500, 0.9),
               price_as_of={"AAPL": NOW - timedelta(days=10)}) == "verouderde_data"


def test_parse_rejects_bad_ai_output():
    raw = ('{"decisions":[{"symbol":"aapl","action":"buy","target_weight":0.5,"confidence":2},'
           '{"symbol":"TSLA","action":"buy","target_weight":0.05,"confidence":0.9},'
           '{"symbol":"SPY","action":"short","target_weight":0.05,"confidence":0.9}]}')
    out = ai.parse(raw, {"AAPL", "SPY"}, 0.10)
    assert len(out) == 1 and out[0]["target_weight"] == 0.10 and out[0]["confidence"] == 1.0


def test_strategy_sells_first_and_respects_direction():
    decs = [{"symbol": "AAPL", "action": "buy", "target_weight": 0.08, "confidence": 0.8},
            {"symbol": "SPY", "action": "sell", "target_weight": 0.0, "confidence": 0.8},
            {"symbol": "MSFT", "action": "sell", "target_weight": 0.09, "confidence": 0.8}]
    props = strategy.proposals(decs, 10_000, {"SPY": 700, "MSFT": 300}, 100)
    assert [(p.symbol, p.side, round(p.notional)) for p in props] == [
        ("SPY", "sell", 700), ("AAPL", "buy", 800)]
