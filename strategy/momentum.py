"""Multi-asset relative momentum, top-3 weighted, with per-slot and all-negative cash rules.

For a lookback of L months, at each month-end t:
    trailing[a] = P_a(t) / P_a(t - L months) - 1         for each asset a in the universe
    if in a cash lock:            100% cash
    elif max(trailing) < 0:       100% cash for the next `cash_months` months (a lock), then re-evaluate
    else:                         rank assets by trailing return (ties broken by universe order) and hold
                                  slot_weights = 50% / 30% / 20% in ranks 1 / 2 / 3 for the whole of month t+1;
                                  a slot whose asset has a negative trailing return is held in CASH instead

Month-end prices are the last adjusted close of each calendar month. The decision at
month-end t uses only prices up to t, and the weights apply from the first trading day
of month t+1, so there is no look-ahead. Cash earns 0%.

The result is a daily matrix of each month's TARGET weights (universe columns + CASH,
rows sum to 1). Returns use monthly rebalancing: the targets are bought at the prior
month-end close and drift with prices within the month, so a month's return equals
Σ w_a × (asset a's month-over-month return). Daily returns follow from that value path,
so the same daily analytics apply as for the MA strategy, and the partial current month
is included.
"""

import pandas as pd

CASH = "CASH"


class MomentumError(ValueError):
    pass


def month_end_prices(prices, universe):
    missing = [a for a in universe if a not in prices.columns]
    if missing:
        raise MomentumError(f"Prices missing for {missing}.")
    return prices[list(universe)].resample("ME").last()


def trailing_returns(monthly, lookback):
    return monthly / monthly.shift(lookback) - 1


def target_weights(row, universe, slot_weights):
    """Ranked top-N weights for one month; negative-return slots go to CASH."""
    ranked = sorted(universe, key=lambda a: (-row[a], universe.index(a)))
    weights = {}
    for asset, w in zip(ranked, slot_weights):
        key = asset if row[asset] >= 0 else CASH
        weights[key] = round(weights.get(key, 0.0) + w, 10)
    return ranked, weights


def run_momentum(prices, lookback, universe, start="2011-01-01", cash_months=3, cost_bps=0.0,
                 slot_weights=(0.5, 0.3, 0.2)):
    """Returns dict with daily weights, daily returns, the month-by-month history and a summary."""
    if lookback < 1:
        raise MomentumError("Lookback must be at least 1 month.")
    if abs(sum(slot_weights) - 1) > 1e-9 or len(slot_weights) > len(universe):
        raise MomentumError("Slot weights must sum to 1 and not exceed the universe size.")
    universe = list(universe)
    monthly = month_end_prices(prices, universe)
    trail = trailing_returns(monthly, lookback)
    start = pd.Timestamp(start)
    decision_ends = [d for d in trail.index if d >= start - pd.offsets.MonthEnd(1)]
    if not decision_ends or trail.loc[decision_ends[0]].isna().any():
        raise MomentumError(f"Not enough history for a {lookback}-month lookback before {start.date()}.")

    history, lock_left = [], 0
    last_month = prices.index.max().to_period("M")
    for d in decision_ends:
        hold_month = (d + pd.offsets.MonthBegin(1)).to_period("M")
        if hold_month > last_month:
            break                                       # no trading days yet for the next month
        row = trail.loc[d]
        ranked = sorted(universe, key=lambda a: (-row[a], universe.index(a)))
        if lock_left > 0:
            weights, lock_left, reason = {CASH: 1.0}, lock_left - 1, "cash lock"
        elif row.max() < 0:
            weights, lock_left, reason = {CASH: 1.0}, cash_months - 1, "all trailing returns negative"
        else:
            ranked, weights = target_weights(row, universe, slot_weights)
            reason = "top 3 weighted" if CASH not in weights else "top 3 weighted; negative slots in cash"
        history.append({"month": str(hold_month), "decided_at": str(d.date()), "weights": weights,
                        "ranked": ranked, "reason": reason,
                        "trailing": {a: round(float(v), 6) for a, v in row.items()}})

    cols = [*universe, CASH]
    month_of_day = prices.index.to_period("M")
    first_day = prices.index[month_of_day >= pd.Period(history[0]["month"])][0]
    weights = pd.DataFrame(0.0, index=prices.index[prices.index >= first_day], columns=cols)
    mod = weights.index.to_period("M")
    for h in history:
        mask = mod == pd.Period(h["month"])
        for a, w in h["weights"].items():
            weights.loc[mask, a] = w

    # Monthly rebalancing: buy the target weights at the prior close, then let holdings drift
    # within the month. The portfolio value relative to the month start is
    # Σ w_a · P_a(t) / P_a(prev close) + w_cash, and daily returns follow from that path.
    px = prices[universe]
    gross = pd.Series(0.0, index=weights.index)
    for h in history:
        days = weights.index[mod == pd.Period(h["month"])]
        if len(days) == 0:
            continue
        base = px.loc[px.index < days[0]].iloc[-1]
        assets = {a: w for a, w in h["weights"].items() if a != CASH}
        value = sum((px.loc[days, a] / base[a]) * w for a, w in assets.items()) + h["weights"].get(CASH, 0.0)
        if not assets:
            value = pd.Series(1.0, index=days)
        gross.loc[days] = value / value.shift(1).fillna(1.0) - 1
    # Turnover = half the sum of absolute changes between monthly TARGET weights (cash included),
    # i.e. the fraction of the portfolio traded. Drift-induced rebalancing is ignored, so with costs
    # at 0 this only drives the cost-sensitivity estimate. The first day is the initial purchase.
    turnover = weights.diff().abs().sum(axis=1) / 2
    turnover.iloc[0] = weights.iloc[0][universe].sum()
    returns = gross - turnover * cost_bps / 10_000.0
    return {"lookback": lookback, "weights": weights, "returns": returns, "history": history,
            "turnover": turnover, "summary": summarize(history, universe, turnover)}


def summarize(history, universe, turnover):
    n = len(history)
    wts = [h["weights"] for h in history]
    keys = [*universe, CASH]
    return {
        "months": n,
        "rebalances": sum(1 for a, b in zip(wts, wts[1:]) if a != b),
        "turnover": float(turnover.sum()),
        "full_cash_months": sum(1 for w in wts if w.get(CASH) == 1.0),
        "partial_cash_months": sum(1 for w in wts if 0 < w.get(CASH, 0) < 1.0),
        "cash_lock_episodes": sum(1 for h in history if h["reason"] == "all trailing returns negative"),
        "avg_weight": {a: sum(w.get(a, 0.0) for w in wts) / n for a in keys if any(a in w for w in wts)},
        "pct_months_held": {a: sum(1 for w in wts if a in w) / n for a in keys if any(a in w for w in wts)},
        "current_weights": wts[-1],
        "current_month": history[-1]["month"],
    }


def run_all_momentum(prices, mcfg):
    return {L: run_momentum(prices, L, mcfg.universe, mcfg.start, mcfg.cash_months, mcfg.cost_bps,
                            mcfg.slot_weights)
            for L in mcfg.lookbacks}


def add_to_returns(returns, results):
    """Add MOM{L} daily returns and w_MOM{L}_{ASSET} weight columns (universe + CASH) to the shared
    returns table. Dates before the momentum start stay NaN."""
    out = returns.copy()
    for L, r in results.items():
        out[f"MOM{L}"] = r["returns"].reindex(out.index)
        for col in r["weights"].columns:
            out[f"w_MOM{L}_{col}"] = r["weights"][col].reindex(out.index)
    return out


def monthly_crosscheck(prices, result):
    """For each month, the compounded daily strategy return must equal Σ w_a × (asset a's
    month-over-month return), with cash at 0%. Returns the worst absolute gap."""
    rets = result["returns"]
    by_month = (1 + rets).groupby(rets.index.to_period("M")).prod() - 1
    universe = [c for c in result["weights"].columns if c != CASH]
    month_close = prices[universe].groupby(prices.index.to_period("M")).last()
    worst = 0.0
    for h in result["history"]:
        m = pd.Period(h["month"])
        if m not in by_month.index:
            continue
        expected = sum(w * (month_close.loc[m, a] / month_close.loc[m - 1, a] - 1)
                       for a, w in h["weights"].items() if a != CASH)
        worst = max(worst, abs(by_month.loc[m] - expected))
    return worst
