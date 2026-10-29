"""Research Agent: runs the strategy grid (round 1) and the Portfolio Manager's proposals (round 2).

Code runs every backtest and computes every statistic (`strategy.ranking`);
the agent decides what to look at, interprets the results, and writes its
findings and a message to the Portfolio Manager Agent. Each saved finding is
checked by the numeric and compliance guardrails before it is accepted.
"""

from strategy.agents import views
from strategy.agents.display import display
from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.config import PORTFOLIOS
from strategy.guardrails import check_text
from strategy.ranking import RankingError, StrategySpec, common_start, grid, rule_text, run_strategy

PROMPT = """You are the Research Agent at Agentic Capital Management, an AI-run research pipeline. You work with the Portfolio Manager Agent in two rounds.

The strategy: {rule}

Round 1: call run_grid, which backtests all {n} combinations ({portfolios}; signals Close and {smas}-day SMA; lookbacks {lookbacks} days) over one common window, alongside SPY and QQQ buy & hold. Study what drives the results: which signals, lookbacks and portfolio rules lead on total return, how the long/short family did, and the trade-offs in drawdown, volatility and Sharpe. Use strategy_detail on a few strategies worth a closer look (for example, which ETFs they actually held). Then call save_research(round=1, ...).

Round 2: call get_proposals to read the Portfolio Manager's {k} new parameter sets, run each with run_strategy, and compare them with the round-1 top {top}. Then call save_research(round=2, ...).

save_research takes:
- findings: 4-8 short bullets for the Portfolio Manager. At least two must start with "Pro:" and at least two with "Con:", covering the strengths and weaknesses of what you found (for example, return vs SPY against deeper drawdowns or higher volatility, how sensitive results are to the lookback, and the fact that many combinations were tested on one historical period).
- message_to_pm: 2-4 sentences addressed to the Portfolio Manager Agent summarizing what you found and what to consider next.

Rules: quote only numbers the tools return, exactly as displayed (percentages to 1 decimal, ratios to 2). Never compute new numbers such as differences or averages yourself. No promises about future returns, no urgency. If save_research rejects your text, fix exactly what it reports and resubmit. When saved, reply with one line."""


def build(ctx, round_):
    """Build the Research Agent for one round.

    Args:
        ctx: the run context.
        round_: 1 (run the grid) or 2 (run the PM's proposals).

    Returns:
        A configured `Agent`.
    """
    cfg = ctx.cfg.ranking

    def need_prices():
        if ctx.prices is None:
            raise ToolError("No dataset loaded. The Data Agent must save one first.")

    def px():
        return ctx.prices[list(cfg.universe)]

    def run_grid():
        need_prices()
        if round_ != 1:
            raise ToolError("run_grid is round 1 only. In round 2, run the Portfolio Manager's proposals.")
        ctx.record("run_grid")
        results = {}
        for spec in grid(cfg):
            rets, picks = run_strategy(px(), spec)
            results[spec.id] = (spec, rets)
            ctx.picks[spec.id] = picks
        ctx.window_start = common_start({sid: r for sid, (_, r) in results.items()})
        views.add_returns(ctx, results)
        ids = [s.id for s in grid(cfg)]
        top = views.ranked(ctx, ids)
        sc = ctx.scores.loc[ids]
        family = {}
        for key, attr in (("by_portfolio", "portfolio"), ("by_signal", "signal_name"), ("by_lookback", "lookback_days")):
            groups = {}
            for sid in ids:
                groups.setdefault(str(getattr(ctx.specs[sid], attr)), []).append(sid)
            family[key] = {g: {"median_total_return": float(sc.loc[m, "total_return"].median()),
                               "best": views.row(ctx, sc.loc[m, "total_return"].idxmax())["label"],
                               "strategies_beating_spy": int((sc.loc[m, "excess_vs_spy"] > 0).sum())}
                           for g, m in groups.items()}
        ctx.facts["round1_family"] = family
        return {"window": views.window(ctx), "strategies": len(ids), "benchmarks": views.benchmarks(ctx),
                "strategies_beating_spy_total_return": int((sc["excess_vs_spy"] > 0).sum()),
                "strategies_beating_qqq_total_return": int((sc["total_return"] > ctx.scores.at["QQQ", "total_return"]).sum()),
                "top_10": top[:10], "bottom_5": top[-5:], "families": display(family)}

    def strategy_detail(id):
        if ctx.scores is None or id not in ctx.specs:
            raise ToolError(f"Unknown strategy {id!r}. Use an id from run_grid or run_strategy.")
        ctx.record("strategy_detail", id=id)
        if id not in ctx.picks:
            ctx.picks[id] = run_strategy(px(), ctx.specs[id])[1]
        picks = views.scored_picks(ctx.picks[id], ctx.window_start)
        led = picks[0].value_counts(normalize=True)
        ctx.facts.setdefault("leader_share", {})[id] = {t: float(v) for t, v in led.items()}
        out = {**views.row(ctx, id), "rebalances": len(picks),
               "share_of_months_each_etf_led": {t: f"{v * 100:.1f}%" for t, v in led.items()},
               "leader_changes": int((picks[0] != picks[0].shift()).iloc[1:].sum()),
               "last_3_picks": {str(d.date()): [x for x in r if isinstance(x, str)] for d, r in picks.tail(3).iterrows()}}
        if "shorts" in picks.columns:
            avg_shorts = float(picks["shorts"].map(len).mean())
            ctx.facts.setdefault("avg_shorts", {})[id] = avg_shorts
            out["avg_etfs_shorted"] = round(avg_shorts, 1)
        return out

    def get_proposals():
        if round_ != 2:
            raise ToolError("There are no proposals in round 1.")
        props = ctx.pm.get("proposals")
        if not props:
            raise ToolError("The Portfolio Manager has not proposed any strategies yet.")
        ctx.record("get_proposals")
        top = ctx.pm["top5"]
        return {"proposals": props, "round1_top": views.ranked(ctx, [p["id"] for p in top]),
                "message_from_pm": ctx.pm.get("message_to_research", "")}

    def run_one(portfolio, sma, lookback_days):
        need_prices()
        if round_ != 2:
            raise ToolError("run_strategy is for the Portfolio Manager's round-2 proposals; use run_grid in round 1.")
        spec = StrategySpec(portfolio, sma, lookback_days)
        proposed = {p["id"] for p in ctx.pm.get("proposals", [])}
        if spec.id not in proposed:
            raise ToolError(f"{spec.id} is not one of the Portfolio Manager's proposals: {sorted(proposed)}.")
        try:
            rets, picks = run_strategy(px(), spec)
            views.add_returns(ctx, {spec.id: (spec, rets)})
        except RankingError as exc:
            raise ToolError(str(exc)) from None
        ctx.picks[spec.id] = picks
        ctx.record("run_strategy", id=spec.id)
        weakest = min(ctx.pm["top5"], key=lambda p: ctx.scores.at[p["id"], "total_return"])["id"]
        return {**views.row(ctx, spec.id), "round1_weakest_top": views.row(ctx, weakest),
                "beats_weakest_top": bool(ctx.scores.at[spec.id, "total_return"] > ctx.scores.at[weakest, "total_return"])}

    def save(round, findings, message_to_pm):
        if round != round_:
            raise ToolError(f"This is round {round_}.")
        if round_ == 1 and "run_grid" not in ctx.calls:
            raise ToolError("Run the grid first.")
        if round_ == 2:
            ran = {c["id"] for c in ctx.calls.get("run_strategy", [])}
            missing = sorted({p["id"] for p in ctx.pm["proposals"]} - ran)
            if missing:
                raise ToolError(f"Run every proposal first; missing {missing}.")
        if not 4 <= len(findings) <= 8:
            raise ToolError("Give 4-8 findings.")
        pros = sum(f.strip().lower().startswith("pro:") for f in findings)
        cons = sum(f.strip().lower().startswith("con:") for f in findings)
        if pros < 2 or cons < 2:
            raise ToolError(f"At least two findings must start with 'Pro:' and two with 'Con:' (got {pros} and {cons}).")
        index = ctx.number_index()
        problems = [f"{t[:60]!r}: {p}" for t in [*findings, message_to_pm] for p in check_text(t, index)]
        if problems:
            raise ToolError("Fix these and resubmit:\n" + "\n".join(problems))
        ids = [s.id for s in grid(cfg)] if round_ == 1 else [p["id"] for p in ctx.pm["proposals"]]
        ctx.research[round_] = {"ids": ids, "findings": findings, "message": message_to_pm}
        ctx.record("save_research", round=round_)
        ctx.say("Research Agent", "Portfolio Manager Agent", round_, message_to_pm, findings)
        views.save_research(ctx)
        return {"saved": ["research.json", "strategy_returns.csv"], "round": round_}

    tools = [
        Tool("strategy_detail", "Detail for one strategy: metrics, how often each ETF was the top pick, leader changes, recent picks.",
             schema({"id": {"type": "string"}}, ["id"]), strategy_detail),
        Tool("save_research", "Save this round's findings and your message to the Portfolio Manager Agent.",
             schema({"round": {"type": "integer", "enum": [round_]},
                     "findings": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 8},
                     "message_to_pm": {"type": "string"}}, ["round", "findings", "message_to_pm"]), save),
    ]
    if round_ == 1:
        tools.insert(0, Tool("run_grid", f"Backtest all {cfg.grid_size} round-1 strategies over the common window and "
                             "return a ranked summary with SPY and QQQ.", schema(), run_grid))
    else:
        tools[:0] = [
            Tool("get_proposals", "Read the Portfolio Manager's proposals and the round-1 top strategies.", schema(), get_proposals),
            Tool("run_strategy", "Backtest one proposed strategy over the common window.",
                 schema({"portfolio": {"type": "string", "enum": list(PORTFOLIOS)},
                         "sma": {"type": "integer", "description": "SMA window in trading days; 0 = the close"},
                         "lookback_days": {"type": "integer"}}, ["portfolio", "sma", "lookback_days"]), run_one),
        ]
    prompt = PROMPT.format(rule=rule_text(cfg), n=cfg.grid_size,
                           portfolios=", ".join(cfg.portfolios), smas="/".join(str(s) for s in cfg.signals if s),
                           lookbacks=", ".join(str(d) for d in cfg.lookbacks), k=cfg.n_proposals, top=cfg.top_n)
    return Agent(ctx.client, "Research Agent", prompt, tools, ctx.trace, effort="medium",
                 max_turns=ctx.cfg.max_turns_per_agent, token_budget=ctx.cfg.token_budget, model=ctx.cfg.model,
                 hooks=ctx.hooks)


def task(ctx, round_):
    """The Research Agent's task message for `round_`."""
    if round_ == 1:
        return (f"The dataset runs from {ctx.prices.index.min().date()} to {ctx.prices.index.max().date()}. "
                "Run round 1 and save your findings for the Portfolio Manager Agent.")
    return ("The Portfolio Manager Agent has proposed new strategies. Run all of them and save your round-2 "
            "findings for the Portfolio Manager Agent.")
