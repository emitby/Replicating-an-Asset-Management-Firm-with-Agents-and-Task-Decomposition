"""Month-end ETF ranking on the close or a simple moving average (SMA).

Ported from `download_prices.ipynb` ("Rank on the moving average instead of the
close" and "Long the top 3, short the losers"), with the same semantics:

- **Signal.** The adjusted close, or its N-trading-day SMA. The SMA only drives
  the ranking; returns are always earned on the actual close.
- **Ranking.** At each month end (the last trading day of each calendar month,
  excluding the current, unfinished month), each ETF's score is the signal's %
  change over a trailing lookback of D calendar days: the signal today divided
  by its value on the last trading day on or before (month end - D days), minus 1.
- **Holding.** The leaders are bought at the month-end close and held to the next
  month end. Weights are set at the month end and then drift with prices (a
  buy-and-hold within each month), so the daily return is the change in the
  weighted value of the basket.
- **Portfolios.** Top 1 (100% in the leader), Top 3 mix (50/30/20 by rank), and
  Long top 3, short negatives (the Top 3 mix plus an equal-weight short leg of
  100% across every other ETF whose score is negative; with none, the month is
  long only). Short P&L is measured on the month-end entry price; borrow costs
  and interest on short proceeds are ignored.
- **Common scoring window.** Strategies with longer SMAs and lookbacks need more
  history before their first pick. Every strategy is scored over the same dates:
  from the day after the latest first pick in round 1 to the last session. A
  round-2 strategy that could not trade on all those dates is rejected.

There are no trading costs (as in the notebook); the PDF discloses this.
"""

from dataclasses import dataclass

import pandas as pd

from strategy.config import LONG_SHORT, PORTFOLIOS, TRADING_DAYS, RankingConfig

PORTFOLIO_CODES = {"Top 1": "T1", "Top 3 mix": "T3", "Long top 3, short negatives": "LS"}
# Columns of the scores table (`score`), in display order.
SCORE_COLS = ["total_return", "excess_vs_spy", "cagr", "max_drawdown", "volatility", "sharpe", "corr_spy"]


class RankingError(ValueError):
    """A strategy specification or dataset that the engine cannot run."""


@dataclass(frozen=True)
class StrategySpec:
    """One strategy: a portfolio rule, a ranking signal and a lookback.

    Attributes:
        portfolio: a key of `config.PORTFOLIOS`.
        sma: SMA window in trading days, or 0 for the raw close.
        lookback_days: calendar days over which the signal's % change is ranked.
    """
    portfolio: str
    sma: int
    lookback_days: int

    @property
    def id(self):
        """Short stable identifier, e.g. ``T3-SMA200-180d`` or ``T1-CLOSE-30d``."""
        signal = "CLOSE" if self.sma == 0 else f"SMA{self.sma}"
        return f"{PORTFOLIO_CODES[self.portfolio]}-{signal}-{self.lookback_days}d"

    @property
    def signal_name(self):
        """Human-readable signal: ``Close`` or ``200d SMA``."""
        return "Close" if self.sma == 0 else f"{self.sma}d SMA"

    @property
    def label(self):
        """Human-readable name used in tables, e.g. ``Top 3 mix | 200d SMA | 180d``."""
        return f"{self.portfolio} | {self.signal_name} | {self.lookback_days}d"

    def to_dict(self):
        """JSON form, including the derived id and label."""
        return {"id": self.id, "label": self.label, "portfolio": self.portfolio, "sma": self.sma,
                "signal": self.signal_name, "lookback_days": self.lookback_days}

    @classmethod
    def from_id(cls, sid):
        """Parse an id produced by `id`.

        Raises:
            RankingError: if the id is malformed or names an unknown portfolio.
        """
        try:
            code, signal, days = sid.split("-")
            portfolio = {v: k for k, v in PORTFOLIO_CODES.items()}[code]
            sma = 0 if signal == "CLOSE" else int(signal.removeprefix("SMA"))
            return cls(portfolio, sma, int(days.removesuffix("d")))
        except (ValueError, KeyError):
            raise RankingError(f"Malformed strategy id {sid!r}.") from None


def rule_text(cfg: RankingConfig):
    """The single authoritative plain-language description of the strategy rule.

    Used by every agent prompt and by the PDF's methodology disclosure, so a rule change
    can't leave a stale description anywhere.
    """
    return (f"At each month end, each of the {len(cfg.universe)} ETFs ({', '.join(cfg.universe)}) is scored by the "
            "% change of its signal (the close, or its N-day simple moving average) over a trailing lookback of "
            "D calendar days. Top 1 holds 100% of the top-ranked ETF; Top 3 mix holds 50%/30%/20% in the top "
            "three; Long top 3, short negatives adds an equal-weight short (100% in total) of every other ETF "
            "with a negative score. Holdings are bought at the month-end close and drift until the next month "
            "end. No trading costs are modeled.")


def grid(cfg: RankingConfig):
    """All round-1 strategies, in table order (portfolio, then signal, then lookback).

    Args:
        cfg: the ranking configuration.

    Returns:
        A list of `StrategySpec`, `cfg.grid_size` long.
    """
    return [StrategySpec(p, s, d) for p in cfg.portfolios for s in cfg.signals for d in cfg.lookbacks]


def month_ends(px):
    """Last trading day of each calendar month, excluding the current (unfinished) month.

    The notebook's rule: a month end equal to the final row of the data is the
    current month, which isn't over yet, so it is not a rebalance date.

    Args:
        px: daily prices indexed by date.

    Returns:
        A DatetimeIndex of month-end trading days.
    """
    ends = px.groupby(px.index.to_period("M")).tail(1).index
    return ends[ends < px.index[-1]]


def signal_frame(px, sma):
    """The ranking signal: the close itself (sma == 0) or its rolling SMA over `sma` trading days."""
    return px if sma == 0 else px.rolling(sma).mean()


def trailing_change(signal, days, ends):
    """% change of `signal` over the trailing `days` calendar days, at each month end.

    The past value is the signal on the last trading day on or before (date - days),
    found with a forward-filled reindex, exactly as in the notebook.

    Args:
        signal: daily signal values, one column per ETF.
        days: calendar-day lookback.
        ends: month-end dates to evaluate.

    Returns:
        A DataFrame indexed by the month ends that have a complete score for every ETF.
    """
    past = signal.reindex(signal.index - pd.Timedelta(days=days), method="ffill").set_axis(signal.index)
    return (signal / past - 1).loc[ends].dropna()


def _period_ends(starts, px):
    """Each holding period runs from one rebalance to the next; the last runs to the final session."""
    return list(starts[1:]) + [px.index[-1]]


def run_long(px, scores, weights):
    """Hold the top-ranked ETFs from each month end to the next, weighted by rank.

    Args:
        px: daily prices of the universe.
        scores: month-end scores from `trailing_change`.
        weights: long weights by rank (top 1 first); they sum to 1.

    Returns:
        (daily returns, picks): picks has one row per month end and one column per rank (0 = leader).
    """
    picks = pd.DataFrame([row.nlargest(len(weights)).index for _, row in scores.iterrows()], index=scores.index)
    rets = []
    for start, end, held in zip(picks.index, _period_ends(picks.index, px), picks.itertuples(index=False)):
        path = px.loc[start:end, list(held)]
        value = (path / path.iloc[0]).mul(list(weights)).sum(axis=1)  # bought at the month-end close, then drifts
        rets.append(value.pct_change().iloc[1:])
    return pd.concat(rets), picks


def run_long_short(px, scores, long_weights):
    """Long the top-ranked ETFs by rank weight; short every other negative-scoring ETF equally.

    Both legs are sized off month-end capital (100% long, 100% short when any ETF
    qualifies) and drift with prices until the next month end. The short leg gains
    when those prices fall. A long holding is never also shorted.

    Args:
        px: daily prices of the universe.
        scores: month-end scores from `trailing_change`.
        long_weights: long weights by rank.

    Returns:
        (daily returns, picks): picks holds the long leg by rank plus a ``shorts`` column (list of tickers).
    """
    rows, rets = [], []
    for (start, row), end in zip(scores.iterrows(), _period_ends(scores.index, px)):
        longs = row.nlargest(len(long_weights)).index
        short = row.index[(row < 0) & ~row.index.isin(longs)]
        moved = px.loc[start:end] / px.loc[start] - 1  # each ETF's cumulative return since the month-end close
        value = 1 + moved[longs].mul(list(long_weights)).sum(axis=1)
        if len(short):
            value -= moved[short].mean(axis=1)  # equal weights summing to 100%
        rets.append(value.pct_change().iloc[1:])
        rows.append([*longs, list(short)])
    picks = pd.DataFrame(rows, index=scores.index, columns=[*range(len(long_weights)), "shorts"])
    return pd.concat(rets), picks


def run_strategy(px, spec, ends=None):
    """Run one strategy over the full price history.

    Args:
        px: daily adjusted closes of the universe (no missing values).
        spec: the strategy to run.
        ends: month-end rebalance dates (default: `month_ends(px)`).

    Returns:
        (daily returns, picks) as from `run_long` or `run_long_short`.

    Raises:
        RankingError: unknown portfolio, a non-positive lookback, a negative SMA, or not enough
            history for even one pick.
    """
    if spec.portfolio not in PORTFOLIOS:
        raise RankingError(f"Unknown portfolio {spec.portfolio!r}. Choose from {list(PORTFOLIOS)}.")
    if spec.lookback_days <= 0 or spec.sma < 0:
        raise RankingError("Lookback must be positive and the SMA window non-negative.")
    ends = month_ends(px) if ends is None else ends
    scores = trailing_change(signal_frame(px, spec.sma), spec.lookback_days, ends)
    if len(scores) < 2:
        raise RankingError(f"{spec.id}: not enough history for the SMA window and lookback.")
    weights = PORTFOLIOS[spec.portfolio]
    if spec.portfolio == LONG_SHORT:
        return run_long_short(px, scores, weights)
    return run_long(px, scores, weights)


def common_start(returns):
    """First date on which every strategy in `returns` (a dict id -> daily returns) has a return."""
    return max(r.index[0] for r in returns.values())


def score(returns, prices, start, rf):
    """Risk and return of each strategy and benchmark over the common window.

    Args:
        returns: dict id -> daily returns.
        prices: daily prices (benchmarks SPY and QQQ are taken from here).
        start: first scored date (from `common_start` of round 1).
        rf: daily risk-free rate (``^IRX / 100 / 252``), aligned to the price index.

    Returns:
        A DataFrame indexed by id with total_return, excess_vs_spy (total-return
        difference vs SPY buy & hold), cagr, max_drawdown, volatility, sharpe and corr_spy
        (correlation of daily returns with SPY's).

    Raises:
        RankingError: if a strategy has no return on some scored date.
    """
    frame = pd.DataFrame(returns).loc[start:]
    missing = [c for c in frame.columns if frame[c].isna().any()]
    if missing:
        raise RankingError(f"Not scored on the common window (insufficient history): {missing}.")
    bench = prices[["SPY", "QQQ"]].pct_change().loc[frame.index]
    frame = frame.join(bench)
    out = pd.DataFrame({
        "total_return": (1 + frame).prod() - 1,
        "cagr": (1 + frame).prod() ** (TRADING_DAYS / len(frame)) - 1,
        "max_drawdown": ((1 + frame).cumprod() / (1 + frame).cumprod().cummax() - 1).min(),
        "volatility": frame.std() * TRADING_DAYS ** 0.5,
    })
    excess = frame.sub(rf.reindex(frame.index).fillna(0.0), axis=0)
    out["sharpe"] = excess.mean() * TRADING_DAYS / out["volatility"]
    out["excess_vs_spy"] = out["total_return"] - out.at["SPY", "total_return"]
    out["corr_spy"] = frame.corrwith(frame["SPY"])   # daily-return correlation with SPY over the same dates
    return out[SCORE_COLS]


def daily_rf(prices):
    """Daily risk-free rate from the 13-week T-bill yield (% annualized): ``^IRX / 100 / 252``."""
    return prices["^IRX"] / 100 / TRADING_DAYS


def top_n(scores, n, ids=None):
    """The n best strategies by total return (ties broken by id, for determinism).

    Args:
        scores: output of `score`; benchmark rows are ignored.
        n: how many to keep.
        ids: restrict to these strategy ids (default: every non-benchmark row).

    Returns:
        A list of ids, best first.
    """
    rows = scores.drop(index=["SPY", "QQQ"], errors="ignore")
    if ids is not None:
        rows = rows.loc[list(ids)]
    ranked = rows.reset_index(names="id").sort_values(["total_return", "id"], ascending=[False, True])
    return list(ranked["id"][:n])


def apply_replacement(scores, top_ids, new_ids):
    """Round-2 rule (user decision): a new strategy that beats the weakest of the current top
    strategies on total return replaces it. Repeated until no new strategy beats the weakest,
    so the result is the best len(top_ids) of the union.

    Args:
        scores: output of `score` covering every id in both lists.
        top_ids: the round-1 top strategies.
        new_ids: the round-2 strategies.

    Returns:
        dict with ``final`` (ids, best first) and ``replacements`` (a list of
        {"added", "removed", "added_total_return", "removed_total_return"} in the order applied).
    """
    current = list(top_ids)
    replacements = []
    for new in sorted(new_ids, key=lambda i: (-scores.at[i, "total_return"], i)):
        weakest = min(current, key=lambda i: (scores.at[i, "total_return"], i))
        if scores.at[new, "total_return"] > scores.at[weakest, "total_return"]:
            current[current.index(weakest)] = new
            replacements.append({"added": new, "removed": weakest,
                                 "added_total_return": float(scores.at[new, "total_return"]),
                                 "removed_total_return": float(scores.at[weakest, "total_return"])})
    final = sorted(current, key=lambda i: (-scores.at[i, "total_return"], i))
    return {"final": final, "replacements": replacements}


def validate_proposal(spec, cfg, existing_ids):
    """Check a round-2 parameter set before it is run.

    Args:
        spec: the proposed strategy.
        cfg: ranking configuration (bounds on SMA and lookback).
        existing_ids: ids already run (round 1 and earlier proposals).

    Raises:
        RankingError: unknown portfolio, SMA or lookback out of bounds, or a duplicate.
    """
    if spec.portfolio not in cfg.portfolios:
        raise RankingError(f"Portfolio must be one of {list(cfg.portfolios)}.")
    lo, hi = cfg.sma_range
    if spec.sma != 0 and not lo <= spec.sma <= hi:
        raise RankingError(f"SMA window must be 0 (the close) or {lo}-{hi} trading days.")
    lo, hi = cfg.lookback_range
    if not lo <= spec.lookback_days <= hi:
        raise RankingError(f"Lookback must be {lo}-{hi} calendar days.")
    if spec.id in existing_ids:
        raise RankingError(f"{spec.id} was already run; propose a new parameter set.")
