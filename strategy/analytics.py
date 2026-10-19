"""Performance and risk metrics over trailing windows.

Conventions:
- Returns are simple daily returns, and growth compounds.
- Annualized figures use 252 trading days, and are reported only for windows of
  12 months or more. Shorter windows report total return only.
- Sharpe and Sortino use excess returns over the daily T-bill rate.
- Beta, correlation and capture ratios are measured against SPY.
"""

import numpy as np
import pandas as pd

from strategy.config import ANNUALIZE_FROM_MONTHS, TRADING_DAYS, WINDOWS

SERIES = ("Strategy", "SPY", "60/40")


def window_slice(df, months):
    if months is None:
        return df
    start = df.index.max() - pd.DateOffset(months=months)
    return df.loc[df.index > start]


def max_drawdown(returns):
    equity = (1 + returns).cumprod()
    dd = equity / equity.cummax() - 1
    return float(dd.min()) if len(dd) else float("nan")


def drawdown_series(returns):
    equity = (1 + returns).cumprod()
    return equity / equity.cummax() - 1


def series_metrics(r, rf, annualize, bench=None):
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


def compute_window(returns, label):
    """Metrics for every series over one trailing window."""
    if label not in WINDOWS:
        raise ValueError(f"Unknown window {label!r}; use one of {list(WINDOWS)}.")
    months = WINDOWS[label]
    df = window_slice(returns, months)
    annualize = months is None or months >= ANNUALIZE_FROM_MONTHS
    out = {"window": label, "start": str(df.index.min().date()), "end": str(df.index.max().date()),
           "annualized": annualize, "series": {}}
    for name in SERIES:
        m = series_metrics(df[name], df["rf"], annualize, bench=df["SPY"])
        if months == 12:
            # A one-year window's annual return IS its total return. Annualizing ~250 trading
            # days would give a second, slightly different "1Y return" and confuse readers.
            m["cagr"] = m["total_return"]
            m["calmar"] = m["cagr"] / abs(m["max_drawdown"]) if m["max_drawdown"] < 0 else float("nan")
        out["series"][name] = m
    w = df["w_spy"]
    out["strategy_activity"] = {
        "switches": int(w.diff().abs().fillna(0).gt(0).sum()),
        "pct_time_in_spy": float(w.mean()),
        "current_allocation_spy": float(w.iloc[-1]),
    }
    out["excess_vs_spy"] = {
        "total_return": out["series"]["Strategy"]["total_return"] - out["series"]["SPY"]["total_return"],
        "max_drawdown": out["series"]["Strategy"]["max_drawdown"] - out["series"]["SPY"]["max_drawdown"],
    }
    if annualize:
        out["excess_vs_spy"]["cagr"] = out["series"]["Strategy"]["cagr"] - out["series"]["SPY"]["cagr"]
    return out


def adverse_windows(analytics):
    """Windows where the strategy was worse than SPY on max drawdown or Sharpe. The deck must
    acknowledge these, so the pitch can't cherry-pick favorable periods."""
    out = []
    for w, data in analytics["windows"].items():
        s, b = data["series"]["Strategy"], data["series"]["SPY"]
        worse = []
        if s["max_drawdown"] < b["max_drawdown"]:
            worse.append("max_drawdown")
        if "sharpe" in s and s["sharpe"] == s["sharpe"] and s["sharpe"] < b["sharpe"]:
            worse.append("sharpe")
        if worse:
            out.append({"window": w, "worse_on": worse})
    return out


def rolling_summary(returns, days=TRADING_DAYS):
    """How often, and by how much, the strategy beat SPY over rolling 1-year periods."""
    roll = (1 + returns[["Strategy", "SPY"]]).rolling(days).apply(np.prod, raw=True) - 1
    roll = roll.dropna()
    diff = roll["Strategy"] - roll["SPY"]
    return {
        "periods": int(len(roll)),
        "pct_periods_beating_spy": float((diff > 0).mean()),
        "worst_1y_strategy": float(roll["Strategy"].min()),
        "worst_1y_spy": float(roll["SPY"].min()),
        "best_1y_strategy": float(roll["Strategy"].max()),
        "best_1y_spy": float(roll["SPY"].max()),
        "median_1y_excess": float(diff.median()),
    }


def growth_of(returns, amount=10_000):
    return {name: float(amount * (1 + returns[name]).prod()) for name in SERIES}


def calendar_year_returns(returns):
    yearly = (1 + returns[list(SERIES)]).groupby(returns.index.year).prod() - 1
    return {int(y): {k: float(v) for k, v in row.items()} for y, row in yearly.iterrows()}
