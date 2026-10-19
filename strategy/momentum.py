"""Multi-asset relative momentum with an absolute-momentum cash rule.

For a lookback of L months, at each month-end t:
    trailing[a] = P_a(t) / P_a(t - L months) - 1           for each asset a in the universe
    if max(trailing) < 0:  hold cash (0% return) for the next `cash_months` months,
                           then re-evaluate at the end of the last cash month
    else:                  hold 100% of argmax(trailing) for the whole of month t+1

Month-end prices are the last adjusted close of each calendar month. The decision
at month-end t uses only prices up to t, and the holding applies from the first
trading day of month t+1, so there is no look-ahead.

The result is a daily weight matrix (one-hot, or all zero in cash). Daily strategy
returns are weights x daily asset returns, so the same analytics (windows,
drawdowns, beta, capture) apply as for the MA strategy, and the partial current
month is included.
"""

import numpy as np
import pandas as pd


class MomentumError(ValueError):
    pass


def month_end_prices(prices, universe):
    missing = [a for a in universe if a not in prices.columns]
    if missing:
        raise MomentumError(f"Prices missing for {missing}.")
    return prices[list(universe)].resample("ME").last()


def trailing_returns(monthly, lookback):
    return monthly / monthly.shift(lookback) - 1


def run_momentum(prices, lookback, universe, start="2011-01-01", cash_months=3, cost_bps=0.0):
    """Returns dict with daily weights, daily returns and the month-by-month decision history."""
    if lookback < 1:
        raise MomentumError("Lookback must be at least 1 month.")
    monthly = month_end_prices(prices, universe)
    trail = trailing_returns(monthly, lookback)
    start = pd.Timestamp(start)
    # Decision month-ends: the month-end before each invested month, from (start - 1 month) onward.
    decision_ends = [d for d in trail.index if d >= start - pd.offsets.MonthEnd(1)]
    first = decision_ends[0]
    if trail.loc[first].isna().any():
        raise MomentumError(f"Not enough history for a {lookback}-month lookback before {start.date()}.")

    history, cash_left = [], 0
    for d in decision_ends:
        hold_month = (d + pd.offsets.MonthBegin(1)).to_period("M")
        if hold_month > prices.index.max().to_period("M"):
            break                                   # no trading days yet for the next month
        row = trail.loc[d]
        if cash_left > 0:
            pick, cash_left, reason = None, cash_left - 1, "cash period"
        elif row.max() < 0:
            pick, cash_left, reason = None, cash_months - 1, "all trailing returns negative"
        else:
            pick, reason = row.idxmax(), "top trailing return"
        history.append({"month": str(hold_month), "decided_at": str(d.date()), "pick": pick or "CASH",
                        "reason": reason, "trailing": {a: round(float(v), 6) for a, v in row.items()}})

    weights = pd.DataFrame(0.0, index=prices.index, columns=list(universe))
    month_of_day = prices.index.to_period("M")
    for h in history:
        if h["pick"] != "CASH":
            weights.loc[month_of_day == pd.Period(h["month"]), h["pick"]] = 1.0
    first_day = prices.index[month_of_day >= pd.Period(history[0]["month"])][0]
    weights = weights.loc[first_day:]

    asset_rets = prices[list(universe)].pct_change().loc[first_day:]
    gross = (weights * asset_rets).sum(axis=1)
    # Turnover: a switch A -> B is one unit traded (|ΔA| + |ΔB| = 2, halved), as in the MA strategy.
    # The first day is the initial purchase. (pandas sums an all-NaN diff row to 0, so set it explicitly.)
    turnover = weights.diff().abs().sum(axis=1) / 2
    turnover.iloc[0] = weights.iloc[0].abs().sum()
    returns = gross - turnover * cost_bps / 10_000.0
    return {"lookback": lookback, "weights": weights, "returns": returns, "history": history,
            "summary": summarize(history, universe)}


def summarize(history, universe):
    picks = [h["pick"] for h in history]
    switches = sum(1 for a, b in zip(picks, picks[1:]) if a != b)
    n = len(picks)
    return {
        "months": n,
        "switches": switches,
        "cash_months": picks.count("CASH"),
        "cash_episodes": sum(1 for h in history if h["reason"] == "all trailing returns negative"),
        "pct_months_by_holding": {a: picks.count(a) / n for a in (*universe, "CASH") if picks.count(a)},
        "current_holding": picks[-1],
        "current_month": history[-1]["month"],
    }


def run_all_momentum(prices, mcfg):
    return {L: run_momentum(prices, L, mcfg.universe, mcfg.start, mcfg.cash_months, mcfg.cost_bps)
            for L in mcfg.lookbacks}


def add_to_returns(returns, results):
    """Add MOM{L} daily returns and hold_MOM{L} (ticker or CASH) columns to the shared returns table.
    Dates before the momentum start stay NaN."""
    out = returns.copy()
    for L, r in results.items():
        w = r["weights"]
        hold = w.idxmax(axis=1).where(w.sum(axis=1) > 0, "CASH")
        out[f"MOM{L}"] = r["returns"].reindex(out.index)
        out[f"hold_MOM{L}"] = hold.reindex(out.index)
    return out


def monthly_crosscheck(prices, result):
    """Independent check: for each invested month, the strategy's compounded daily return
    must equal the held asset's month-over-month return (or 0 in cash)."""
    rets = result["returns"]
    by_month = (1 + rets).groupby(rets.index.to_period("M")).prod() - 1
    universe = list(result["weights"].columns)
    month_close = prices[universe].resample("ME").last()
    month_close.index = month_close.index.to_period("M")
    worst = 0.0
    for h in result["history"]:
        m = pd.Period(h["month"])
        if m not in by_month.index:
            continue
        if h["pick"] == "CASH":
            expected = 0.0
        else:
            prev = m - 1
            # The month's last close (or latest close for a partial month) vs the prior month-end.
            expected = month_close.loc[m, h["pick"]] / month_close.loc[prev, h["pick"]] - 1
        worst = max(worst, abs(by_month.loc[m] - expected))
    return worst
