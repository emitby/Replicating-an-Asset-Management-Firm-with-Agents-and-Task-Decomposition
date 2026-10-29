"""Performance, risk and portfolio-fit metrics for the final strategies and the benchmarks.

Conventions:
- Returns are simple daily returns, and growth compounds.
- Annualized figures use 252 trading days, and are reported only for windows of
  12 months or more. A one-year window's annual return is its total return.
- Sharpe and Sortino use excess returns over the daily T-bill rate (``rf`` column).
- Beta, correlation and capture ratios are measured against SPY.
- Portfolio fit: correlations of daily returns over the scored window, and a
  blend of SPY with a strategy, rebalanced daily to fixed weights (a
  simplification that the PDF discloses).
"""

import numpy as np
import pandas as pd

from strategy.config import ANNUALIZE_FROM_MONTHS, BENCHMARKS, TRADING_DAYS, WINDOWS

FIT_ASSETS = ("SPY", "QQQ", "TLT", "GLD")   # correlation partners for the portfolio-fit analysis


def window_slice(df, months):
    """The trailing `months` calendar months of `df` (all of it when months is None)."""
    if months is None:
        return df
    start = df.index.max() - pd.DateOffset(months=months)
    return df.loc[df.index > start]


def max_drawdown(returns):
    """Largest peak-to-trough fall of the compounded return series (a negative number)."""
    equity = (1 + returns).cumprod()
    dd = equity / equity.cummax() - 1
    return float(dd.min()) if len(dd) else float("nan")


def drawdown_series(returns):
    """Daily drawdown from the running peak of the compounded return series."""
    equity = (1 + returns).cumprod()
    return equity / equity.cummax() - 1


def series_metrics(r, rf, annualize, bench=None):
    """Return and risk metrics of one daily return series.

    Args:
        r: daily returns.
        rf: daily risk-free rate (aligned to r; missing days count as 0).
        annualize: add CAGR, volatility, Sharpe, Sortino, max drawdown and Calmar.
        bench: optional benchmark returns for beta, correlation and capture ratios.

    Returns:
        A dict of floats (total_return, days, ... as applicable).
    """
    r = r.dropna()
    rf = rf.reindex(r.index).fillna(0.0)
    n = len(r)
    years = n / TRADING_DAYS
    total = float((1 + r).prod() - 1)
    excess = r - rf
    downside = excess.clip(upper=0)
    m = {"total_return": total, "days": n}
    if annualize:
        cagr = float((1 + total) ** (1 / years) - 1) if years > 0 else float("nan")
        vol = float(r.std() * np.sqrt(TRADING_DAYS))
        dd_dev = float(np.sqrt((downside ** 2).mean()) * np.sqrt(TRADING_DAYS))
        mdd = max_drawdown(r)
        m.update(
            cagr=cagr, volatility=vol,
            sharpe=float(excess.mean() * TRADING_DAYS / vol) if vol > 0 else float("nan"),
            sortino=float(excess.mean() * TRADING_DAYS / dd_dev) if dd_dev > 0 else float("nan"),
            max_drawdown=mdd,
            calmar=float(cagr / abs(mdd)) if mdd < 0 else float("nan"),
        )
    else:
        m["max_drawdown"] = max_drawdown(r)
        m["volatility"] = float(r.std() * np.sqrt(TRADING_DAYS))
    m["hit_rate"] = float((r > 0).mean())
    m["best_day"], m["worst_day"] = float(r.max()), float(r.min())
    if bench is not None:
        b = bench.reindex(r.index)
        var = b.var()
        m["beta"] = float(r.cov(b) / var) if var > 0 else float("nan")
        m["correlation"] = float(r.corr(b))
        up, down = b > 0, b < 0
        m["up_capture"] = float(r[up].mean() / b[up].mean()) if up.any() else float("nan")
        m["down_capture"] = float(r[down].mean() / b[down].mean()) if down.any() else float("nan")
    return m


def compute_window(returns, label, series):
    """Metrics for each of `series` over one trailing window.

    Args:
        returns: daily returns with the series columns plus ``SPY`` and ``rf``.
        label: a key of `config.WINDOWS`.
        series: column names to measure (final strategy ids and benchmarks).

    Returns:
        {"window", "start", "end", "annualized", "series": {name: metrics}}.
    """
    months = WINDOWS[label]
    df = window_slice(returns, months)
    annualize = months is None or months >= ANNUALIZE_FROM_MONTHS
    out = {"window": label, "start": str(df.index.min().date()), "end": str(df.index.max().date()),
           "annualized": annualize, "series": {}}
    for name in series:
        m = series_metrics(df[name], df["rf"], annualize, bench=df["SPY"])
        if months == 12:
            # A one-year window's annual return IS its total return. Annualizing ~250 trading
            # days would give a second, slightly different "1Y return" and confuse readers.
            m["cagr"] = m["total_return"]
            m["calmar"] = m["cagr"] / abs(m["max_drawdown"]) if m["max_drawdown"] < 0 else float("nan")
        out["series"][name] = m
    return out


def growth_of(returns, series, amount=10_000):
    """Final value of `amount` invested in each series over the whole scored window."""
    return {name: float(amount * (1 + returns[name]).prod()) for name in series}


def calendar_year_returns(returns, series):
    """Compounded return of each series in each calendar year (the last year is year-to-date)."""
    yearly = (1 + returns[list(series)]).groupby(returns.index.year).prod() - 1
    return {int(y): {k: float(v) for k, v in row.items()} for y, row in yearly.iterrows()}


def portfolio_fit(returns, prices, strategy_ids, weight):
    """How each final strategy fits next to the asset classes an investor already holds.

    Args:
        returns: daily returns over the scored window (strategy columns, SPY, rf).
        prices: daily prices (for TLT and GLD returns).
        strategy_ids: the final strategies.
        weight: the strategy's share in a SPY + strategy blend (e.g. 0.2 for 80/20).

    Returns:
        {"blend_weight", "correlation": {id: {asset: corr}},
         "blends": {id: metrics of the blend}, "spy": metrics of SPY alone}.
    """
    assets = prices[list(FIT_ASSETS)].pct_change().reindex(returns.index)
    corr = {sid: {a: float(returns[sid].corr(assets[a])) for a in FIT_ASSETS} for sid in strategy_ids}
    rf = returns["rf"]
    blends = {}
    for sid in strategy_ids:
        mix = (1 - weight) * returns["SPY"] + weight * returns[sid]   # rebalanced daily to fixed weights
        blends[sid] = series_metrics(mix, rf, True, bench=returns["SPY"])
    return {"blend_weight": weight, "correlation": corr, "blends": blends,
            "spy": series_metrics(returns["SPY"], rf, True)}


def report_series(final_ids):
    """Column order used by every analytics table and chart: the final strategies, then the benchmarks."""
    return [*final_ids, *BENCHMARKS]
