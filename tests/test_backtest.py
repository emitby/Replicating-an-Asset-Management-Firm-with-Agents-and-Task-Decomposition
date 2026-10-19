import numpy as np
import pandas as pd
import pytest

from strategy.backtest import (common_start, ma_signal, portfolio_returns, run_all, walk_forward,
                               weights_for)
from strategy.config import StrategyConfig


def tiny_prices(spy, ief=None):
    idx = pd.bdate_range("2020-01-01", periods=len(spy))
    ief = ief if ief is not None else [100.0] * len(spy)
    return pd.DataFrame({"SPY": spy, "IEF": ief, "^IRX": [0.0] * len(spy)}, index=idx)


def test_signal_matches_hand_calculation():
    close = pd.Series([10, 11, 12, 9, 13], dtype=float)
    sig = ma_signal(close, 3)
    # SMA3: nan, nan, 11, 10.667, 11.333
    assert sig.iloc[:2].isna().all()
    assert sig.iloc[2:].tolist() == [1.0, 0.0, 1.0]


def test_weights_apply_next_day():
    p = tiny_prices([10, 11, 12, 9, 13, 14])
    w = weights_for(p, 3)
    sig = ma_signal(p["SPY"], 3)
    assert w.iloc[3] == sig.iloc[2] and w.iloc[4] == sig.iloc[3]


def test_portfolio_returns_and_costs():
    p = tiny_prices([100, 110, 99], ief=[100, 100, 101])
    w = pd.Series([np.nan, 1.0, 0.0], index=p.index)
    r = portfolio_returns(p, w, cost_bps=10)
    assert r.iloc[1] == pytest.approx(0.10)                 # fully in SPY, no change from NaN start
    assert r.iloc[2] == pytest.approx(0.01 - 0.001)         # switched to IEF: IEF +1% minus 10 bps


def test_no_look_ahead(prices):
    """Changing prices after day T must not change any weight or return up to day T."""
    cfg = StrategyConfig()
    cut = prices.index[3000]
    shocked = prices.copy()
    shocked.loc[shocked.index > cut, "SPY"] *= 3.0
    for n in cfg.ma_windows:
        a, b = weights_for(prices, n).loc[:cut], weights_for(shocked, n).loc[:cut]
        pd.testing.assert_series_equal(a, b)
    ra = portfolio_returns(prices, weights_for(prices, 50), 5).loc[:cut]
    rb = portfolio_returns(shocked, weights_for(shocked, 50), 5).loc[:cut]
    pd.testing.assert_series_equal(ra, rb)


def test_walk_forward_selection_uses_only_prior_data(prices):
    cfg = StrategyConfig()
    base = walk_forward(prices, cfg.ma_windows, cfg.cost_bps, cfg.min_train_years)
    year = base["selection_history"][5]["year"]
    shocked = prices.copy()
    shocked.loc[shocked.index >= f"{year}-01-01", "SPY"] *= np.linspace(1, 5, (shocked.index >= f"{year}-01-01").sum())
    alt = walk_forward(shocked, cfg.ma_windows, cfg.cost_bps, cfg.min_train_years)
    picks = lambda wf: [h["chosen_ma"] for h in wf["selection_history"] if h["year"] <= year]
    assert picks(base) == picks(alt)


def test_walk_forward_structure(backtest_result, prices):
    wf, returns = backtest_result
    cfg = StrategyConfig()
    start = common_start(prices, cfg.ma_windows)
    assert wf["oos_start"].year >= start.year + cfg.min_train_years
    for h in wf["selection_history"]:
        assert h["chosen_ma"] in cfg.ma_windows
        assert pd.Timestamp(h["train_end"]) < pd.Timestamp(f"{h['year']}-01-01")
        best = max(h["train_sharpe"].values())
        assert h["train_sharpe"][str(h["chosen_ma"])] == best
    assert returns.index.min() == wf["oos_start"]
    assert set(returns.columns) >= {"Strategy", "SPY", "60/40", "MA5", "MA200", "w_spy", "rf"}
    assert returns["w_spy"].isin([0.0, 1.0]).all()


def test_stitched_weights_follow_chosen_ma(backtest_result):
    wf, returns = backtest_result
    for h in wf["selection_history"]:
        mask = returns.index.year == h["year"]
        cand_w = wf["candidates"][h["chosen_ma"]][0].reindex(returns.index[mask])
        pd.testing.assert_series_equal(returns["w_spy"][mask], cand_w, check_names=False)


def test_strategy_returns_reproducible(prices, backtest_result):
    _, again = run_all(prices, StrategyConfig())
    pd.testing.assert_frame_equal(backtest_result[1], again)
