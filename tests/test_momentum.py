"""Momentum v2: top-3 weighted 50/30/20, per-slot cash, 3-month all-negative lock."""

import numpy as np
import pandas as pd
import pytest

from strategy.config import MomentumConfig
from strategy.momentum import MomentumError, monthly_crosscheck, run_all_momentum, run_momentum

UNIVERSE = ("SPY", "QQQ", "TLT", "GLD", "IWM", "IEF")
SLOTS = (0.5, 0.3, 0.2)


def staircase(monthly_growth, start="2008-01-01", months=60):
    """Daily prices where asset a grows by monthly_growth[a](month_start_date) each month, flat within months."""
    days = pd.bdate_range(start, periods=months * 22)
    df = pd.DataFrame(index=days)
    for a, g in monthly_growth.items():
        level, vals = 100.0, []
        for i, d in enumerate(days):
            if i and d.month != days[i - 1].month:
                level *= 1 + g(d)
            vals.append(level)
        df[a] = vals
    return df


def const(x):
    return lambda d: x


@pytest.fixture(scope="module")
def prices():
    from strategy.data import clean, synthetic_prices
    return clean(synthetic_prices())


def month(r, m):
    return next(h for h in r["history"] if h["month"] == m)


def test_top_three_get_50_30_20():
    growth = {"QQQ": 0.03, "GLD": 0.02, "IWM": 0.01, "SPY": 0.005, "TLT": 0.002, "IEF": 0.001}
    p = staircase({a: const(g) for a, g in growth.items()})
    r = run_momentum(p, 3, UNIVERSE, start="2009-01-01")
    h = month(r, "2009-06")
    assert h["weights"] == {"QQQ": 0.5, "GLD": 0.3, "IWM": 0.2}
    assert h["ranked"][:3] == ["QQQ", "GLD", "IWM"]
    days = r["weights"].index[r["weights"].index.to_period("M") == pd.Period("2009-06")]
    np.testing.assert_allclose(r["weights"].loc[days].sum(axis=1), 1.0)
    assert (r["weights"].loc[days, "QQQ"] == 0.5).all() and (r["weights"].loc[days, "CASH"] == 0).all()


@pytest.mark.parametrize("negatives, expected", [
    ({"IWM"}, {"QQQ": 0.5, "GLD": 0.3, "CASH": 0.2}),                 # 3rd negative -> its 20% in cash
    ({"GLD", "IWM"}, {"QQQ": 0.5, "CASH": 0.5}),                      # 2nd and 3rd negative
])
def test_per_slot_cash(negatives, expected):
    growth = {"QQQ": 0.03, "GLD": 0.02, "IWM": 0.01, "SPY": -0.02, "TLT": -0.03, "IEF": -0.04}
    for a in negatives:
        growth[a] = -0.005 if a == "IWM" else -0.001
    p = staircase({a: const(g) for a, g in growth.items()})
    r = run_momentum(p, 3, UNIVERSE, start="2009-01-01")
    h = month(r, "2009-06")
    assert h["weights"] == expected
    assert h["reason"] == "top 3 weighted; negative slots in cash"


def test_all_negative_locks_cash_three_months_then_resumes():
    def down_then_spy_up(asset):
        def g(d):
            if pd.Timestamp("2011-01-01") <= d < pd.Timestamp("2011-04-01"):
                return -0.05 if asset == "SPY" else -0.04
            return 0.03 if asset == "SPY" else 0.0
        return g
    p = staircase({a: down_then_spy_up(a) for a in UNIVERSE})
    r = run_momentum(p, 3, UNIVERSE, start="2010-06-01", cash_months=3)
    assert month(r, "2011-02")["weights"].get("CASH", 0) < 1          # not yet all negative
    for m in ("2011-03", "2011-04", "2011-05"):
        assert month(r, m)["weights"] == {"CASH": 1.0}
    assert month(r, "2011-03")["reason"] == "all trailing returns negative"
    assert month(r, "2011-04")["reason"] == month(r, "2011-05")["reason"] == "cash lock"
    # End of May: only SPY positive over 3 months -> SPY gets slot 1, slots 2-3 (non-positive) in cash.
    june = month(r, "2011-06")["weights"]
    assert june["SPY"] == 0.5 and june["CASH"] == pytest.approx(0.5)
    assert (r["returns"].loc["2011-03-01":"2011-05-31"] == 0).all()


def test_one_month_lookback_supported(prices):
    r = run_momentum(prices, 1, UNIVERSE, start="2011-01-01")
    assert r["history"][0]["month"] == "2011-01" and r["history"][0]["decided_at"] == "2010-12-31"
    monthly = prices[list(UNIVERSE)].resample("ME").last()
    trail = monthly / monthly.shift(1) - 1
    h = r["history"][10]
    row = trail.loc[pd.Timestamp(h["decided_at"])]
    assert h["ranked"] == list(row.sort_values(ascending=False, kind="stable").index)


def test_no_look_ahead(prices):
    base = run_momentum(prices, 12, UNIVERSE)
    cut = pd.Timestamp("2015-06-30")
    shocked = prices.copy()
    shocked.loc[shocked.index > cut, "GLD"] *= 10
    alt = run_momentum(shocked, 12, UNIVERSE)
    before = lambda r: [h["weights"] for h in r["history"] if h["decided_at"] <= "2015-06-30"]
    assert before(base) == before(alt)
    pd.testing.assert_series_equal(base["returns"].loc[:cut], alt["returns"].loc[:cut])


def test_monthly_rebalancing_with_drift(prices):
    """Targets are bought at the prior close and drift within the month: the first day's return is the
    target-weighted asset return, and the month compounds to the weighted monthly asset returns."""
    r = run_momentum(prices, 6, UNIVERSE)
    assets = prices[list(UNIVERSE)].pct_change()
    np.testing.assert_allclose(r["weights"].sum(axis=1), 1.0)
    for h in r["history"][3:10]:
        days = r["returns"].index[r["returns"].index.to_period("M") == pd.Period(h["month"])]
        first = days[0]
        expected_first = sum(w * assets.loc[first, a] for a, w in h["weights"].items() if a != "CASH")
        assert r["returns"].loc[first] == pytest.approx(expected_first)
    assert monthly_crosscheck(prices, r) < 1e-12


def test_turnover_and_costs():
    growth = {"QQQ": 0.03, "GLD": 0.02, "IWM": 0.01, "SPY": 0.005, "TLT": 0.002, "IEF": 0.001}
    p = staircase({a: const(g) for a, g in growth.items()})
    gross = run_momentum(p, 3, UNIVERSE, start="2009-01-01")
    net = run_momentum(p, 3, UNIVERSE, start="2009-01-01", cost_bps=10)
    diff = gross["returns"] - net["returns"]
    assert diff.iloc[0] == pytest.approx(0.001)                         # initial buy of 100%
    assert (diff.iloc[1:] == 0).all()                                   # same weights every month
    assert gross["summary"]["turnover"] == pytest.approx(1.0)
    assert gross["summary"]["rebalances"] == 0


def test_monthly_crosscheck_matches(prices):
    for L, r in run_all_momentum(prices, MomentumConfig()).items():
        assert monthly_crosscheck(prices, r) < 1e-10, L


def test_summary(prices):
    s = run_momentum(prices, 12, UNIVERSE)["summary"]
    assert abs(sum(s["avg_weight"].values()) - 1) < 1e-12
    assert set(s["current_weights"]) <= set(UNIVERSE) | {"CASH"}
    assert all(0 <= v <= 1 for v in s["pct_months_held"].values())


def test_insufficient_history_rejected(prices):
    with pytest.raises(MomentumError, match="history"):
        run_momentum(prices, 24, UNIVERSE, start="2003-06-01")


@pytest.fixture(scope="module")
def combined(prices):
    from strategy.backtest import run_all
    from strategy.config import StrategyConfig
    from strategy.momentum import add_to_returns
    _, returns = run_all(prices, StrategyConfig())
    return add_to_returns(returns, run_all_momentum(prices, MomentumConfig()))


def test_comparison_includes_qqq_and_all_lookbacks(combined):
    from strategy.analytics import comparison_window
    from strategy.config import COMPARISON_WINDOWS
    lbs = MomentumConfig().lookbacks
    for label in COMPARISON_WINDOWS:
        out = comparison_window(combined, label, lbs)
        assert set(out["series"]) == {*(f"MOM{L}" for L in lbs), "MA Strategy", "SPY", "QQQ"}
        assert set(out["momentum_activity"]) == {f"MOM{L}" for L in lbs}
    s2011 = comparison_window(combined, "S2011", lbs)
    qqq = (1 + combined["QQQ"].loc[s2011["start"]:]).prod() - 1
    assert s2011["series"]["QQQ"]["total_return"] == pytest.approx(qqq)


def test_weight_columns_match_history(combined, prices):
    r = run_momentum(prices, 3, UNIVERSE)
    for h in r["history"][:24]:
        days = combined.index[combined.index.to_period("M") == pd.Period(h["month"])]
        for a, w in h["weights"].items():
            assert (combined.loc[days, f"w_MOM3_{a}"] == w).all()
    assert combined.loc[:"2010-12-31", "MOM3"].isna().all()
