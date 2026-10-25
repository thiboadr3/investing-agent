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
