import numpy as np
import pandas as pd
import pytest

from strategy.analytics import (compute_window, max_drawdown, rolling_summary, series_metrics,
                                window_slice)
from strategy.config import WINDOWS


def test_max_drawdown_hand_example():
    r = pd.Series([0.10, -0.50, 0.20])      # equity 1.1 -> 0.55 -> 0.66
    assert max_drawdown(r) == pytest.approx(-0.5)


def test_constant_return_metrics():
    idx = pd.bdate_range("2020-01-01", periods=252)
    r = pd.Series(0.001, index=idx)
    rf = pd.Series(0.0, index=idx)
    m = series_metrics(r, rf, annualize=True)
    assert m["total_return"] == pytest.approx(1.001 ** 252 - 1)
    assert m["cagr"] == pytest.approx(1.001 ** 252 - 1)
    assert m["max_drawdown"] == 0
    assert m["hit_rate"] == 1.0


def test_sharpe_formula():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2020-01-01", periods=1000)
    r = pd.Series(rng.normal(0.0005, 0.01, 1000), index=idx)
    rf = pd.Series(0.0001, index=idx)
    m = series_metrics(r, rf, annualize=True)
    expected = (r - rf).mean() * 252 / (r.std() * np.sqrt(252))
    assert m["sharpe"] == pytest.approx(expected)


def test_beta_against_itself_is_one():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2020-01-01", periods=500)
    b = pd.Series(rng.normal(0, 0.01, 500), index=idx)
    m = series_metrics(b, pd.Series(0.0, index=idx), annualize=True, bench=b)
    assert m["beta"] == pytest.approx(1.0) and m["correlation"] == pytest.approx(1.0)
    assert m["up_capture"] == pytest.approx(1.0) and m["down_capture"] == pytest.approx(1.0)


def test_window_slicing(backtest_result):
    _, returns = backtest_result
    end = returns.index.max()
    s = window_slice(returns, 12)
    assert s.index.min() > end - pd.DateOffset(months=12)
    assert (s.index.min() - (end - pd.DateOffset(months=12))).days <= 5


def test_all_windows(backtest_result):
    _, returns = backtest_result
    for label in WINDOWS:
        out = compute_window(returns, label)
        assert set(out["series"]) == {"Strategy", "SPY", "60/40"}
        assert out["annualized"] == (label != "3M")
        assert ("cagr" in out["series"]["Strategy"]) == out["annualized"]
    with pytest.raises(ValueError):
        compute_window(returns, "2Y")


def test_one_year_return_is_total_return(backtest_result):
    """Regression: a slide said SPY 1Y = 16.8% (total) while the table said 16.9% (annualized)."""
    out = compute_window(backtest_result[1], "1Y")
    for m in out["series"].values():
        assert m["cagr"] == m["total_return"]


def test_adverse_windows_flags_where_strategy_is_worse():
    from strategy.analytics import adverse_windows
    a = {"windows": {
        "5Y": {"series": {"Strategy": {"max_drawdown": -0.26, "sharpe": 0.39}, "SPY": {"max_drawdown": -0.24, "sharpe": 0.57}}},
        "SI": {"series": {"Strategy": {"max_drawdown": -0.26, "sharpe": 0.6}, "SPY": {"max_drawdown": -0.55, "sharpe": 0.5}}},
    }}
    assert adverse_windows(a) == [{"window": "5Y", "vs": "SPY", "worse_on": ["max_drawdown", "sharpe"]}]
    a["windows"]["SI"]["series"]["60/40"] = {"max_drawdown": -0.31, "sharpe": 0.63, "cagr": 0.084}
    a["windows"]["SI"]["series"]["Strategy"]["cagr"] = 0.076
    assert {"window": "SI", "vs": "60/40", "worse_on": ["cagr", "sharpe"]} in adverse_windows(a)


def test_rolling_summary_bounds(backtest_result):
    s = rolling_summary(backtest_result[1])
    assert 0 <= s["pct_periods_beating_spy"] <= 1
    assert s["worst_1y_strategy"] <= s["best_1y_strategy"]
