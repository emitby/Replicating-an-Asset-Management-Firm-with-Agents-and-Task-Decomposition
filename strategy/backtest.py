"""Moving-average rotation backtest with walk-forward selection.

Rule for a single moving average of length N:
    signal[t] = 1 if SPY close[t] > SMA_N(SPY)[t] else 0
    weight_SPY[t+1] = signal[t]           (decided at close t, held during day t+1)
    weight_IEF = 1 - weight_SPY

Returns on day t use only the weight decided at close t-1, so there is no
look-ahead. Turnover costs `cost_bps` per unit of weight change.

Walk-forward: on the first trading day of each calendar year Y, compare the
candidates' Sharpe ratios over all history before Y (at least
`min_train_years`). Trade the winner's weights during Y. Stitching those yearly
weights gives a fully out-of-sample strategy.
"""

import numpy as np
import pandas as pd

from strategy.config import RATE_TICKER, RISK_ASSET, SAFE_ASSET, TRADING_DAYS


def daily_rf(prices):
    """Daily risk-free return from the 13-week T-bill yield (% annualized)."""
    return prices[RATE_TICKER] / 100.0 / TRADING_DAYS


def asset_returns(prices):
    return prices[[RISK_ASSET, SAFE_ASSET]].pct_change()


def ma_signal(close, n):
    """1.0 when close > N-day SMA, 0.0 when not, NaN until the SMA exists."""
    sma = close.rolling(n, min_periods=n).mean()
    sig = (close > sma).astype(float)
    return sig.where(sma.notna())


def weights_for(prices, n):
    """SPY weight held on each day: yesterday's signal."""
    return ma_signal(prices[RISK_ASSET], n).shift(1)


def portfolio_returns(prices, w_spy, cost_bps):
    """Daily returns for a SPY/IEF portfolio with SPY weight `w_spy`, net of costs."""
    r = asset_returns(prices)
    gross = w_spy * r[RISK_ASSET] + (1 - w_spy) * r[SAFE_ASSET]
    turnover = w_spy.diff().abs().fillna(0.0)
    return gross - turnover * cost_bps / 10_000.0


def sharpe(returns, rf):
    excess = (returns - rf.reindex(returns.index)).dropna()
    sd = excess.std()
    if len(excess) < 2 or not sd > 0:
        return float("nan")
    return float(excess.mean() / sd * np.sqrt(TRADING_DAYS))


def common_start(prices, ma_windows):
    """First day on which every candidate has a weight, so all are compared on the same days."""
    longest = max(ma_windows)
    return weights_for(prices, longest).first_valid_index()


def run_ma_backtest(prices, n, cost_bps, start=None):
    w = weights_for(prices, n)
    rets = portfolio_returns(prices, w, cost_bps)
    if start is not None:
        w, rets = w.loc[start:], rets.loc[start:]
    return w, rets


def walk_forward(prices, ma_windows, cost_bps, min_train_years):
    start = common_start(prices, ma_windows)
    rf = daily_rf(prices)
    cand_w, cand_r = {}, {}
    for n in ma_windows:
        cand_w[n], cand_r[n] = run_ma_backtest(prices, n, cost_bps, start)

    first_year = (start + pd.DateOffset(years=min_train_years)).year + 1
    last_year = prices.index.max().year
    if first_year > last_year:
        raise ValueError("Not enough history for walk-forward selection.")

    history, chosen_w = [], []
    for year in range(first_year, last_year + 1):
        cutoff = pd.Timestamp(f"{year}-01-01")
        train = {n: sharpe(cand_r[n].loc[:cutoff - pd.Timedelta(days=1)], rf) for n in ma_windows}
        best = max(ma_windows, key=lambda n: (np.nan_to_num(train[n], nan=-np.inf), -n))
        year_mask = cand_w[best].index.year == year
        chosen_w.append(cand_w[best][year_mask])
        history.append({"year": year, "chosen_ma": best,
                        "train_start": str(start.date()), "train_end": str((cutoff - pd.Timedelta(days=1)).date()),
                        "train_sharpe": {str(n): round(train[n], 4) for n in ma_windows}})

    w_strategy = pd.concat(chosen_w)
    oos_start = w_strategy.index.min()
    # Recompute on the stitched weights so a change of MA at a year boundary pays its trading cost.
    full_w = pd.concat([cand_w[history[0]["chosen_ma"]].loc[:oos_start].iloc[:-1], w_strategy])
    r_strategy = portfolio_returns(prices.loc[full_w.index], full_w, cost_bps).loc[oos_start:]
    return {
        "oos_start": oos_start, "selection_history": history,
        "weights": w_strategy, "returns": r_strategy,
        "candidates": {n: (cand_w[n], cand_r[n]) for n in ma_windows},
        "common_start": start,
    }


def benchmark_returns(prices, mix=(0.6, 0.4)):
    r = asset_returns(prices)
    return {
        "SPY": r[RISK_ASSET],
        "60/40": mix[0] * r[RISK_ASSET] + mix[1] * r[SAFE_ASSET],   # daily rebalanced
    }


def candidate_table(prices, wf, rf):
    """Full-period (IN-SAMPLE) statistics for each single-MA rule, from the walk-forward start."""
    from strategy.analytics import series_metrics
    oos = wf["oos_start"]
    rows = {}
    for n, (w, r) in wf["candidates"].items():
        r = r.loc[oos:]
        m = series_metrics(r, rf.loc[oos:], annualize=True)
        m["switches"] = int(w.loc[oos:].diff().abs().fillna(0).gt(0).sum())
        m["pct_time_in_spy"] = float(w.loc[oos:].mean())
        rows[f"MA{n}"] = m
    return rows


def run_all(prices, cfg):
    """Everything the Backtest agent's tools need, computed once."""
    wf = walk_forward(prices, cfg.ma_windows, cfg.cost_bps, cfg.min_train_years)
    bench = benchmark_returns(prices, cfg.benchmark_mix)
    oos = wf["oos_start"]
    returns = pd.DataFrame({"Strategy": wf["returns"],
                            "SPY": bench["SPY"].loc[oos:],
                            "60/40": bench["60/40"].loc[oos:]}).dropna()
    for n, (_, r) in wf["candidates"].items():
        returns[f"MA{n}"] = r.loc[oos:]
    returns["w_spy"] = wf["weights"].reindex(returns.index)
    returns["rf"] = daily_rf(prices).reindex(returns.index)
    return wf, returns
