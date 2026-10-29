import numpy as np
import pandas as pd
import pytest

from strategy.analytics import (compute_window, max_drawdown, portfolio_fit, series_metrics,
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


def test_window_slicing(offline_run):
    r = offline_run.returns
    one_year = window_slice(r, 12)
    assert one_year.index.min() > r.index.max() - pd.DateOffset(months=12)
    assert window_slice(r, None).equals(r)


def test_all_windows_and_one_year_total_return(offline_run):
    an = offline_run.analytics
    series = an["series"]
    assert len(series) == 7 and series[-2:] == ["SPY", "QQQ"]
    for w in WINDOWS:
        assert set(an["windows"][w]["series"]) == set(series)
    one = an["windows"]["1Y"]["series"]["SPY"]
    assert one["cagr"] == one["total_return"]


def test_portfolio_fit(offline_run):
    r = offline_run.returns
    final = offline_run.pm["final"]["final"]
    fit = portfolio_fit(r, offline_run.prices, final, 0.2)
    sid = final[0]
    assert fit["correlation"][sid]["SPY"] == pytest.approx(r[sid].corr(r["SPY"]))
    mix = 0.8 * r["SPY"] + 0.2 * r[sid]
    assert fit["blends"][sid]["total_return"] == pytest.approx((1 + mix).prod() - 1)
    assert fit["spy"]["total_return"] == pytest.approx((1 + r["SPY"]).prod() - 1)
