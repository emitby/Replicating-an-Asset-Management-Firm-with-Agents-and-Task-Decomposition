"""Research state helpers and display-ready views shared by the Research, PM, Analytics and Presentation Agents.

The agents only ever see rounded views (`display.display`), and every view is
built here from the same `ctx.scores` table, so all agents quote identical figures.
"""

import pandas as pd

from strategy.agents.display import display
from strategy.config import BENCHMARKS
from strategy.paths import write_json, write_text
from strategy.ranking import daily_rf, score

METRIC_COLS = ["total_return", "excess_vs_spy", "cagr", "max_drawdown", "volatility", "sharpe", "corr_spy"]


def add_returns(ctx, results):
    """Add strategy runs to the context and rescore every strategy over the common window.

    Args:
        ctx: the run context (needs prices and, after round 1, window_start).
        results: dict id -> (spec, daily returns).

    Side effects:
        Updates ctx.specs, ctx.returns (strategy columns plus SPY, QQQ and rf) and ctx.scores.
    """
    with ctx.lock:
        existing = {} if ctx.returns is None else {c: ctx.returns[c] for c in ctx.returns.columns if c in ctx.specs}
        series = existing | {sid: rets for sid, (_, rets) in results.items()}
        rf = daily_rf(ctx.prices)
        ctx.scores = score(series, ctx.prices, ctx.window_start, rf)   # raises if any strategy misses a date
        ctx.specs.update({sid: spec for sid, (spec, _) in results.items()})
        frame = pd.DataFrame(series).loc[ctx.window_start:]
        ctx.returns = frame.join(ctx.prices[list(BENCHMARKS)].pct_change()).join(rf.rename("rf"))


def row(ctx, sid, rank=None):
    """Display view of one strategy (or benchmark): its label and rounded metrics."""
    label = ctx.specs[sid].label if sid in ctx.specs else f"{sid} buy & hold"
    out = {"id": sid, "label": label, **display(ctx.scores.loc[sid, METRIC_COLS].to_dict())}
    if rank is not None:
        out = {"rank": rank, **out}
    return out


def ranked(ctx, ids):
    """Display rows for `ids`, best total return first, with their rank among `ids`."""
    order = ctx.scores.loc[list(ids)].sort_values("total_return", ascending=False).index
    return [row(ctx, sid, i + 1) for i, sid in enumerate(order)]


def benchmarks(ctx):
    """Display rows for SPY and QQQ buy & hold."""
    return [row(ctx, b) for b in BENCHMARKS]


def window(ctx):
    """The common scoring window as text, e.g. ``2016-05-02 to 2026-10-28``."""
    return f"{ctx.returns.index.min().date()} to {ctx.returns.index.max().date()}"


def scored_picks(picks, window_start):
    """The picks that were held during the scored window: from the last pick before its start onward."""
    first = picks.index[picks.index < window_start][-1]
    return picks.loc[first:]


def leader_mix(picks, window_start):
    """Share of scored months each ETF was the top-ranked pick (display-ready, best first)."""
    led = scored_picks(picks, window_start)[0].value_counts(normalize=True)
    return {t: f"{v * 100:.0f}%" for t, v in led.items()}


def save_research(ctx):
    """Write research.json (specs, scores, rounds) and strategy_returns.csv into the run folder."""
    write_json(ctx.path("research.json"), {
        "window_start": str(ctx.window_start.date()), "window_end": str(ctx.returns.index.max().date()),
        "strategies": {sid: s.to_dict() for sid, s in ctx.specs.items()},
        "scores": {sid: {k: float(v) for k, v in r.items()} for sid, r in ctx.scores.iterrows()},
        "rounds": ctx.research,
        "facts": ctx.facts,
    })
    write_text(ctx.path("strategy_returns.csv"), ctx.returns.to_csv())
