from datetime import datetime, timedelta, timezone

from agent import ai, rules, strategy
from agent.broker import norm_symbol
from agent.config import Risk
from agent.data import Snapshot, build_snapshot
from agent.db import DB
from agent.risk import Context, Proposal, check_order
from agent.shadow import Shadows

NOW = datetime(2026, 10, 22, 15, tzinfo=timezone.utc)
R = Risk(max_drawdown_pct=15, max_position_pct=10, min_cash_pct=5, max_orders_per_day=10,
         min_order_usd=100, min_ai_confidence=0.6, max_data_age_hours=96,
         max_crypto_data_age_hours=36, max_crypto_total_pct=20, max_crypto_position_pct=12)


def ctx(**kw):
    base = dict(equity=10_000, cash=10_000, peak_equity=10_000, position_values={},
                position_qty={}, open_order_symbols=set(),
                universe={"AAPL", "SPY", "BTC/USD", "ETH/USD"},
                orders_today=0, market_open=True, account_ok=True, stop_file=False,
                price_as_of={"AAPL": NOW - timedelta(hours=1), "SPY": NOW,
                             "BTC/USD": NOW, "ETH/USD": NOW})
    base.update(kw)
    return Context(**base)


def chk(p, **kw):
    return check_order(p, ctx(**kw), R, now=NOW)


# ---------- risicolaag ----------
def test_ok_buy():
    assert chk(Proposal("AAPL", "buy", 900, 1.0)) is None


def test_position_limit():
    assert chk(Proposal("AAPL", "buy", 1500, 1.0)) == "max_positiegrootte"


def test_drawdown_blocks_buys_not_sells():
    kw = dict(equity=8_400, peak_equity=10_000, position_values={"AAPL": 500},
              position_qty={"AAPL": 2})
    assert chk(Proposal("SPY", "buy", 500, 1.0), **kw) == "max_terugval_bereikt"
    assert chk(Proposal("AAPL", "sell", 500, 1.0), **kw) is None


def test_no_shorts():
    assert chk(Proposal("AAPL", "sell", 500, 1.0)) == "geen_positie_om_te_verkopen"


def test_misc_rules():
    assert chk(Proposal("TSLA", "buy", 500, 1.0)) == "niet_in_universum"
    assert chk(Proposal("AAPL", "buy", 500, 1.0), stop_file=True) == "noodstop_actief"
    assert chk(Proposal("AAPL", "buy", 500, 1.0), market_open=False) == "markt_gesloten"
    assert chk(Proposal("AAPL", "buy", 500, 0.5)) == "te_lage_zekerheid"
    assert chk(Proposal("AAPL", "buy", 500, 1.0), cash=600) == "cashbuffer"
    assert chk(Proposal("AAPL", "buy", 500, 1.0), open_order_symbols={"AAPL"}) == "open_order_bestaat_al"
    assert chk(Proposal("AAPL", "buy", 500, 1.0),
               price_as_of={"AAPL": NOW - timedelta(days=10)}) == "verouderde_data"


def test_crypto_rules():
    # 24/7: crypto mag als de beurs dicht is, aandelen niet
    assert chk(Proposal("BTC/USD", "buy", 1000, 1.0), market_open=False) is None
    # per munt max 12%, samen max 20%
    assert chk(Proposal("BTC/USD", "buy", 1300, 1.0)) == "max_positiegrootte"
    assert chk(Proposal("ETH/USD", "buy", 1100, 1.0),
               position_values={"BTC/USD": 1000}) == "max_crypto_aandeel"
    # strengere data-ouderdom voor crypto
    assert chk(Proposal("BTC/USD", "buy", 500, 1.0),
               price_as_of={"BTC/USD": NOW - timedelta(hours=40)}) == "verouderde_data"


def test_norm_symbol():
    assert norm_symbol("BTCUSD", "crypto") == "BTC/USD"
    assert norm_symbol("BTC/USD", "crypto") == "BTC/USD"
    assert norm_symbol("AAPL", "us_equity") == "AAPL"


# ---------- regels ----------
def snap(sym, above=True, mom=0.2, r3=0.1, vol=0.2, crypto=False):
    return Snapshot(sym, 100, NOW, 0.01, r3, 0.2, above, vol, mom, crypto)


def test_build_snapshot_basics():
    closes = [100 * 1.001 ** i for i in range(300)]
    s = build_snapshot("X", closes, NOW, crypto=False)
    assert s.above_200d is True and s.mom_12_1 > 0 and s.ret_12m > s.mom_12_1


def test_stock_rules_filter_and_cap():
    snaps = {s.symbol: s for s in [snap("A", mom=0.5, vol=0.1), snap("B", mom=0.3),
                                   snap("C", above=False), snap("D", mom=-0.1)]}
    w, why = rules.stock_targets(snaps, 0.95, top_n=10, cap=0.10)
    assert set(w) == {"A", "B"} and all(v <= 0.10 for v in w.values())
    assert "200d" in why["C"] and "momentum" in why["D"]


def test_crypto_trend_scales_budget():
    both = {"BTC/USD": snap("BTC/USD", crypto=True, vol=0.5),
            "ETH/USD": snap("ETH/USD", crypto=True, vol=0.7)}
    w, _ = rules.crypto_targets(both, 0.20, 0.12)
    assert abs(sum(w.values()) - 0.20) < 1e-3 and max(w.values()) <= 0.12
    one = dict(both, **{"ETH/USD": snap("ETH/USD", above=False, crypto=True)})
    w1, _ = rules.crypto_targets(one, 0.20, 0.12)
    assert list(w1) == ["BTC/USD"] and w1["BTC/USD"] <= 0.12
    none = {k: snap(k, above=False, crypto=True) for k in both}
    assert rules.crypto_targets(none, 0.20, 0.12)[0] == {}


def test_total_targets_never_exceed_invested():
    snaps = {f"S{i}": snap(f"S{i}", mom=0.1 + i / 100) for i in range(15)}
    snaps["BTC/USD"] = snap("BTC/USD", crypto=True, vol=0.5)
    w, _ = rules.targets(snaps, {"target_invested_pct": 95, "stock_top_n": 10}, 0.10, 0.20, 0.12)
    assert sum(w.values()) <= 0.9501 and len([s for s in w if "/" not in s]) == 10


# ---------- AI-uitvoer ----------
def test_filter_can_only_reduce():
    raw = ('{"crypto_factor": 0.2, "adjustments": ['
           '{"symbol":"AAPL","factor":0.5,"reason":"onderzoek"},'
           '{"symbol":"MSFT","factor":0.0,"reason":"niet in doel"},'
           '{"symbol":"SPY","factor":3,"reason":"meer!"},'
           '{"symbol":"BTC/USD","factor":0.1,"reason":"hack"}]}')
    f, cf, notes, _ = ai.parse_filter(raw, {"AAPL", "SPY", "BTC/USD"})
    assert f == {"AAPL": 0.5, "BTC/USD": 0.0} and cf == 0.5


def test_free_parse_caps_and_normalises():
    raw = ('{"targets":[{"symbol":"btc/usd","weight":0.9},{"symbol":"AAPL","weight":0.25},'
           '{"symbol":"SPY","weight":0.25},{"symbol":"TSLA","weight":0.2},'
           '{"symbol":"QQQ","weight":0.25},{"symbol":"IWM","weight":0.25}]}')
    w, _ = ai.parse_free(raw, {"BTC/USD", "AAPL", "SPY", "QQQ", "IWM"}, 0.25)
    assert "TSLA" not in w and max(w.values()) <= 0.25 and sum(w.values()) <= 0.9501


# ---------- strategie ----------
def test_proposals_sell_first_and_full_exit():
    props = strategy.proposals({"AAPL": 0.08}, 10_000, {"SPY": 700, "AAPL": 0},
                               {"AAPL", "SPY"}, 100)
    assert [(p.symbol, p.side, round(p.notional)) for p in props] == [
        ("SPY", "sell", 700), ("AAPL", "buy", 800)]
    assert strategy.proposals({"AAPL": 0.08}, 10_000, {}, {"AAPL"}, 100, allow_buys=False) == []


# ---------- schaduwportefeuilles ----------
def test_shadow_rebalance_costs_and_value(tmp_path):
    sh = Shadows(DB(tmp_path / "t.db"), {"stock": 0.05, "crypto": 0.25})
    sh.ensure("x", 10_000)
    sh.rebalance("x", {"AAPL": 0.5, "BTC/USD": 0.2}, {"AAPL": 100, "BTC/USD": 50_000})
    s = sh._load("x")
    assert abs(s["h"]["AAPL"] * 100 - 5000) < 1 and abs(s["h"]["BTC/USD"] * 50_000 - 2000) < 1
    assert abs(s["costs"] - (5000 * 0.0005 + 2000 * 0.0025)) < 0.01
    sh.mark({"AAPL": 110, "BTC/USD": 50_000})
    out = sh.summary()[0]
    assert out["value"] > 10_000 and out["return"] > 0
    sh.rebalance("x", {}, {"AAPL": 110, "BTC/USD": 50_000})   # alles verkopen
    assert sh._load("x")["h"] == {}


def test_buffer_keeps_held_position():
    snaps = {f"S{i}": snap(f"S{i}", mom=1 - i / 20) for i in range(8)}
    w0, _ = rules.stock_targets(snaps, 0.95, top_n=3, cap=0.5)
    assert set(w0) == {"S0", "S1", "S2"}
    # S5 al in bezit: zonder buffer valt hij weg, met buffer 3 (top 6) blijft hij
    w1, _ = rules.stock_targets(snaps, 0.95, top_n=3, cap=0.5, held={"S5"}, buffer=0)
    w2, _ = rules.stock_targets(snaps, 0.95, top_n=3, cap=0.5, held={"S5"}, buffer=3)
    assert "S5" not in w1 and "S5" in w2 and len(w2) == 3


def test_band_skips_small_adjustments():
    # bestaande positie 8% -> doel 10%: afwijking 2% < band 3% -> geen order; nieuwe positie wel
    props = strategy.proposals({"AAPL": 0.10, "SPY": 0.05}, 10_000, {"AAPL": 800},
                               {"AAPL", "SPY"}, 100, band=0.03)
    assert [(p.symbol, p.side) for p in props] == [("SPY", "buy")]
