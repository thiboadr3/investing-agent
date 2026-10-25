from datetime import datetime, timezone

from agent import rules
from agent.data import Snapshot, build_snapshot
from agent.universe import is_common_stock


def asset(sym, name, exch="NASDAQ", frac=True, trad=True):
    return {"symbol": sym, "name": name, "exchange": exch, "fractionable": frac, "tradable": trad}


def test_common_stock_filter():
    assert is_common_stock(asset("PLTR", "Palantir Technologies Inc. Class A Common Stock"))
    assert is_common_stock(asset("BRK.B", "Berkshire Hathaway Inc. Class B", "NYSE"))
    assert not is_common_stock(asset("QQQ", "Invesco QQQ Trust, Series 1 ETF"))
    assert not is_common_stock(asset("SPY", "SPDR S&P 500 ETF Trust", "ARCA"))
    assert not is_common_stock(asset("ABCDW", "Abc Corp Warrants"))
    assert not is_common_stock(asset("XYZ", "Xyz Corp", frac=False))
    assert not is_common_stock(asset("XYZ", "Xyz Corp", exch="OTC"))


def snap(sym, m12, m6, vol=0.3):
    return Snapshot(sym, 10, datetime.now(timezone.utc), 0, 0, 0, True, vol, m12, mom_6_1=m6)


def test_score_key_exclude_and_max_vol():
    snaps = {s.symbol: s for s in [snap("A", 0.9, 0.1), snap("B", 0.2, 0.8),
                                   snap("SPY", 0.5, 0.9), snap("C", 0.1, 0.7, vol=2.5)]}
    w, why = rules.stock_targets(snaps, 0.95, 1, 0.2, score_key="mom6", exclude={"SPY"},
                                 max_vol=1.5)
    assert list(w) == ["B"]
    assert "te beweeglijk" in why["C"]
    w12, _ = rules.stock_targets(snaps, 0.95, 1, 0.2, score_key="mom12", exclude={"SPY"})
    assert list(w12) == ["A"]


def test_mom6_matches_backtest_definition():
    closes = [100 + i for i in range(300)]
    s = build_snapshot("X", closes, datetime.now(timezone.utc), False)
    assert abs(s.mom_6_1 - (closes[-22] / closes[-127] - 1)) < 1e-12


def test_parse_pick_limits():
    import json
    from agent.ai import parse_pick
    raw = json.dumps({"market_view": "x", "positions": [
        {"symbol": "A", "weight": 0.5, "company": "A Inc", "bull": "b"},
        {"symbol": "B", "weight": 0.3}, {"symbol": "C", "weight": 0.3},
        {"symbol": "HACK", "weight": 0.2}],
        "sells": [{"symbol": "OLD", "reason": "trend kapot"}]})
    w, fiches, sells, view = parse_pick(raw, {"A", "B", "C"}, 0.2, 0.95, 10)
    assert set(w) == {"A", "B", "C"} and all(v <= 0.2 for v in w.values())
    assert "HACK" not in w and sells == {"OLD": "trend kapot"} and fiches["A"]["company"] == "A Inc"
    w2, *_ = parse_pick(raw, {"A", "B", "C"}, 0.5, 0.6, 2)
    assert len(w2) == 2 and abs(sum(w2.values()) - 0.6) < 1e-3


def test_shortlist_includes_held():
    snaps = {s.symbol: s for s in [snap("A", 0.9, 0.1), snap("B", 0.2, 0.8),
                                   snap("SPY", 0.5, 0.9), snap("H", -0.1, -0.2),
                                   snap("QQQ", 0.1, 0.1)]}
    snaps["H"].name = "Held Corp"          # gewoon aandeel; QQQ heeft geen naam (ETF)
    out = rules.shortlist(snaps, 1, {"score": "mom6"}, {"H", "QQQ"}, "SPY")
    assert out == ["B", "H"]
