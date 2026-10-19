import numpy as np
import pandas as pd
import pytest

from strategy.config import MomentumConfig
from strategy.momentum import MomentumError, monthly_crosscheck, run_all_momentum, run_momentum

UNIVERSE = ("SPY", "QQQ", "TLT", "GLD", "IWM", "IEF")


def staircase(monthly_growth, start="2008-01-01", months=60):
    """Daily prices where asset a grows by monthly_growth[a](month_index) each month, flat within months."""
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


@pytest.fixture(scope="module")
def prices():
    from strategy.data import clean, synthetic_prices
    return clean(synthetic_prices())


def test_picks_best_trailing_and_applies_next_month(prices):
    r = run_momentum(prices, 6, UNIVERSE, start="2011-01-01")
    monthly = prices[list(UNIVERSE)].resample("ME").last()
    trail = monthly / monthly.shift(6) - 1
    for h in r["history"][:30]:
        row = trail.loc[pd.Timestamp(h["decided_at"])]
        assert h["pick"] == ("CASH" if h["reason"] != "top trailing return" else row.idxmax())
        if h["pick"] != "CASH":
            days = r["weights"].index[r["weights"].index.to_period("M") == pd.Period(h["month"])]
            assert (r["weights"].loc[days, h["pick"]] == 1).all()
            assert (r["weights"].loc[days].sum(axis=1) == 1).all()


def test_first_invested_month_is_january_2011(prices):
    r = run_momentum(prices, 24, UNIVERSE, start="2011-01-01")
    assert r["history"][0]["month"] == "2011-01"
    assert r["history"][0]["decided_at"] == "2010-12-31"
    assert r["weights"].index.min().strftime("%Y-%m") == "2011-01"


def test_no_look_ahead(prices):
    base = run_momentum(prices, 12, UNIVERSE)
    cut = pd.Timestamp("2015-06-30")
    shocked = prices.copy()
    shocked.loc[shocked.index > cut, "GLD"] *= 10            # GLD rockets afterwards
    alt = run_momentum(shocked, 12, UNIVERSE)
    upto = [h["pick"] for h in base["history"] if h["decided_at"] <= "2015-06-30"]
    assert upto == [h["pick"] for h in alt["history"] if h["decided_at"] <= "2015-06-30"]
    pd.testing.assert_series_equal(base["returns"].loc[:cut], alt["returns"].loc[:cut])


def test_cash_rule_three_months_then_resume():
    # Everything falls in Jan-Mar 2011 (so the 3-month trailing return at end-Mar is negative),
    # then SPY recovers strongly.
    def g_spy(d):
        return -0.05 if pd.Timestamp("2011-01-01") <= d < pd.Timestamp("2011-04-01") else 0.03

    def g_other(d):
        return -0.04 if pd.Timestamp("2011-01-01") <= d < pd.Timestamp("2011-04-01") else 0.0

    p = staircase({a: (g_spy if a == "SPY" else g_other) for a in UNIVERSE})
    r = run_momentum(p, 3, UNIVERSE, start="2010-06-01", cash_months=3)
    by_month = {h["month"]: h for h in r["history"]}
    # End of Feb 2011: 3-month trailing (Dec +3%, Jan -5%, Feb -5% for SPY; others negative) is
    # negative for all six assets -> cash in Mar, Apr, May.
    assert by_month["2011-02"]["pick"] != "CASH"
    assert [by_month[m]["pick"] for m in ("2011-03", "2011-04", "2011-05")] == ["CASH"] * 3
    assert by_month["2011-03"]["reason"] == "all trailing returns negative"
    assert by_month["2011-04"]["reason"] == by_month["2011-05"]["reason"] == "cash period"
    # Re-evaluated at end of May 2011 (Mar -5%, Apr +3%, May +3% for SPY): back in SPY in June.
    assert by_month["2011-06"]["pick"] == "SPY"
    cash_days = r["returns"].loc["2011-03-01":"2011-05-31"]
    assert (cash_days == 0).all() and len(cash_days) > 50


def test_daily_returns_equal_held_asset(prices):
    r = run_momentum(prices, 3, UNIVERSE)
    assets = prices[list(UNIVERSE)].pct_change()
    for h in r["history"][5:15]:
        days = r["returns"].index[r["returns"].index.to_period("M") == pd.Period(h["month"])]
        expected = 0.0 if h["pick"] == "CASH" else assets.loc[days, h["pick"]]
        np.testing.assert_allclose(r["returns"].loc[days], expected)


def test_monthly_crosscheck_matches(prices):
    for L, r in run_all_momentum(prices, MomentumConfig()).items():
        assert monthly_crosscheck(prices, r) < 1e-10, L


def test_summary_counts(prices):
    s = run_momentum(prices, 12, UNIVERSE)["summary"]
    assert s["months"] == len(run_momentum(prices, 12, UNIVERSE)["history"])
    assert abs(sum(s["pct_months_by_holding"].values()) - 1) < 1e-12
    assert s["cash_months"] >= 3 * s["cash_episodes"] - 2   # last episode may be truncated by today


@pytest.fixture(scope="module")
def combined(prices):
    from strategy.backtest import run_all
    from strategy.config import StrategyConfig
    from strategy.momentum import add_to_returns
    _, returns = run_all(prices, StrategyConfig())
    return add_to_returns(returns, run_all_momentum(prices, MomentumConfig()))


def test_comparison_windows(combined):
    from strategy.analytics import comparison_window
    from strategy.config import COMPARISON_WINDOWS
    for label in COMPARISON_WINDOWS:
        out = comparison_window(combined, label, (3, 6, 12, 24))
        assert set(out["series"]) == {"MOM3", "MOM6", "MOM12", "MOM24", "MA Strategy", "SPY"}
        assert out["start"] >= "2011-01-01"
        assert set(out["momentum_activity"]) == {"MOM3", "MOM6", "MOM12", "MOM24"}
    one_year = comparison_window(combined, "1Y", (3, 6, 12, 24))
    for m in one_year["series"].values():
        assert m["cagr"] == m["total_return"]
    s2011 = comparison_window(combined, "S2011", (3, 6, 12, 24))
    assert s2011["start"][:7] == "2011-01"
    # The MA strategy in the comparison is the same series, just restricted to 2011+.
    ma = (1 + combined["Strategy"].loc[s2011["start"]:]).prod() - 1
    assert s2011["series"]["MA Strategy"]["total_return"] == pytest.approx(ma)


def test_hold_columns_match_history(combined, prices):
    r = run_momentum(prices, 12, UNIVERSE)
    for h in r["history"][:24]:
        days = combined.index[combined.index.to_period("M") == pd.Period(h["month"])]
        assert (combined.loc[days, "hold_MOM12"] == h["pick"]).all()
    assert combined.loc[:"2010-12-31", "MOM12"].isna().all()


def test_insufficient_history_rejected(prices):
    with pytest.raises(MomentumError, match="history"):
        run_momentum(prices, 24, UNIVERSE, start="2003-06-01")


def test_costs_only_on_switches():
    p = staircase({a: (lambda d: 0.02) if a == "QQQ" else (lambda d: 0.0) for a in UNIVERSE})
    gross = run_momentum(p, 3, UNIVERSE, start="2009-01-01")["returns"]
    net = run_momentum(p, 3, UNIVERSE, start="2009-01-01", cost_bps=10)["returns"]
    diff = (gross - net)
    assert diff.iloc[0] == pytest.approx(0.001)              # initial purchase
    assert (diff.iloc[1:] == 0).all()                        # always QQQ: no further trades
