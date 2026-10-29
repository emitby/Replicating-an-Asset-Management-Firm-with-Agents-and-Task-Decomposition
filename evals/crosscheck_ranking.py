"""Independent cross-check: the research notebook's own code, re-run against the pipeline's results.

`notebook_returns` reproduces `download_prices.ipynb` cells 17, 25 and 27
(`month_ends`, `trailing_change`, `month_end_mix`, `month_end_long_short`)
almost verbatim. It deliberately imports nothing from `strategy.ranking`, so a
bug in the engine can't hide in a shared helper (lesson: an independent
implementation is cheap insurance).
"""

import pandas as pd

PORTFOLIO_WEIGHTS = {"T1": (1.0,), "T3": (0.5, 0.3, 0.2), "LS": (0.5, 0.3, 0.2)}


def _month_ends(close):
    month_ends = close.groupby(close.index.to_period("M")).tail(1).index
    return month_ends[month_ends < close.index[-1]]  # the current month isn't over yet


def _trailing_change(signal, days, month_ends):
    past = signal.reindex(signal.index - pd.Timedelta(days=days), method="ffill").set_axis(signal.index)
    return (signal / past - 1).loc[month_ends].dropna()


def _month_end_mix(px, signal, days, weights, month_ends):
    trailing = _trailing_change(signal, days, month_ends)
    picks = pd.DataFrame([row.nlargest(len(weights)).index for _, row in trailing.iterrows()], index=trailing.index)
    period_ends = list(picks.index[1:]) + [px.index[-1]]
    rets = []
    for start, end, held in zip(picks.index, period_ends, picks.itertuples(index=False)):
        path = px.loc[start:end, list(held)]
        value = (path / path.iloc[0]).mul(list(weights)).sum(axis=1)
        rets.append(value.pct_change().iloc[1:])
    return pd.concat(rets)


def _month_end_long_short(px, signal, days, long_weights, month_ends):
    trailing = _trailing_change(signal, days, month_ends)
    period_ends = list(trailing.index[1:]) + [px.index[-1]]
    rets = []
    for (start, row), end in zip(trailing.iterrows(), period_ends):
        longs = row.nlargest(len(long_weights)).index
        short = row.index[(row < 0) & ~row.index.isin(longs)]
        moved = px.loc[start:end] / px.loc[start] - 1
        value = 1 + moved[longs].mul(list(long_weights)).sum(axis=1)
        if len(short):
            value -= moved[short].mean(axis=1)
        rets.append(value.pct_change().iloc[1:])
    return pd.concat(rets)


def notebook_returns(close, sid):
    """Daily returns of strategy `sid` (e.g. ``T3-SMA200-180d``) computed the notebook's way.

    Args:
        close: daily adjusted closes of the universe, no missing values.
        sid: a strategy id: portfolio code (T1, T3, LS), signal (CLOSE or SMA<n>), lookback (<days>d).

    Returns:
        A Series of daily returns.
    """
    code, signal_code, days = sid.split("-")
    n = 0 if signal_code == "CLOSE" else int(signal_code[3:])
    signal = close if n == 0 else close.rolling(n).mean()
    ends = _month_ends(close)
    fn = _month_end_long_short if code == "LS" else _month_end_mix
    return fn(close, signal, int(days[:-1]), PORTFOLIO_WEIGHTS[code], ends)


def crosscheck(prices, returns, universe, tol=1e-10):
    """Compare every strategy column of the pipeline's saved returns with the notebook implementation.

    Args:
        prices: the run's prices.csv.
        returns: the run's strategy_returns.csv (strategy columns plus SPY, QQQ, rf).
        universe: the ETF tickers.
        tol: maximum absolute difference in any daily return.

    Returns:
        {"checked": n, "max_abs_diff": float, "mismatched": [ids]}.
    """
    close = prices[list(universe)].dropna()
    ids = [c for c in returns.columns if c not in ("SPY", "QQQ", "rf")]
    worst, bad = 0.0, []
    for sid in ids:
        ref = notebook_returns(close, sid).reindex(returns.index)
        diff = float((ref - returns[sid]).abs().max())
        worst = max(worst, diff)
        if not diff <= tol:
            bad.append(sid)
    return {"checked": len(ids), "max_abs_diff": worst, "mismatched": bad}
