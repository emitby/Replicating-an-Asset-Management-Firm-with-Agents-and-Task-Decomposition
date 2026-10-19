"""Analytics Agent: performance and risk over 3M, 1Y, 3Y, 5Y and since inception."""

from strategy.agents.display import display
from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.analytics import (calendar_year_returns, comparison_extras, comparison_window, compute_window,
                                growth_of, rolling_summary)
from strategy.config import COMPARISON_WINDOWS, WINDOWS
from strategy.guardrails import check_text
from strategy.paths import write_json

PROMPT = """You are the Analytics Agent in an investment research pipeline. You analyze the out-of-sample performance of a strategy that switches between SPY and IEF on a walk-forward-selected moving average. You compare it with SPY buy-and-hold and a 60/40 SPY/IEF mix.

Your job:
1. Compute metrics for every window: 3M, 1Y, 3Y, 5Y and SI (since the walk-forward start). 3M shows total returns only. Longer windows are annualized.
2. Run the rolling and calendar-year analysis.
3. Compute the head-to-head comparison (compute_comparison) for every window: 3M, 1Y, 3Y, 5Y and S2011 (since January 2011). It covers:
   - the five monthly MOMENTUM sub-strategies (MOM1, MOM3, MOM6, MOM12, MOM24), each holding 50/30/20 in the top three trailing performers among SPY, QQQ, TLT, GLD, IWM and IEF. Negative slots are held in cash, with a 3-month all-cash lock when all six are negative.
   - the MA trend strategy
   - two buy-and-hold benchmarks, SPY and QQQ
   Note that momentum has no modeled trading costs, while the MA strategy is net of costs.
4. Save 5 to 9 findings: one sentence each, specific and balanced. Cover where the MA strategy helped and where it lagged, how the momentum lookbacks differ from each other, and how they compare with SPY, QQQ and the MA strategy. At least two findings must be about momentum, and at least one must compare against QQQ. An investment committee will read them.

Rules: quote numbers exactly as the tools display them (percentages to 1 decimal, ratios to 2), or rounded further. Never compute new numbers yourself: no differences, averages or ratios that a tool didn't return. Saving checks every number and rejects any it can't find in the results. Don't promise future returns."""


def build(ctx):
    def need_returns():
        if ctx.returns is None:
            raise ToolError("No backtest returns loaded. The Backtest Agent must save first.")

    def metrics(window):
        need_returns()
        if window not in WINDOWS:
            raise ToolError(f"Windows are {list(WINDOWS)}.")
        ctx.record("compute_metrics", window=window)
        result = compute_window(ctx.returns, window)
        with ctx.lock:
            ctx.analytics = ctx.analytics or {"windows": {}}
            ctx.analytics["windows"][window] = result
        return display(result)

    def rolling():
        need_returns()
        ctx.record("rolling_analysis")
        extra = {"rolling_1y": rolling_summary(ctx.returns), "growth_of_10000": growth_of(ctx.returns),
                 "calendar_years": calendar_year_returns(ctx.returns)}
        with ctx.lock:
            ctx.analytics = ctx.analytics or {"windows": {}}
            ctx.analytics.update(extra)
        shown = display(extra)
        shown["growth_of_10000"] = {k: f"${v:,.0f}" for k, v in extra["growth_of_10000"].items()}
        shown["calendar_years"] = {y: {k: f"{v * 100:.1f}%" for k, v in row.items()}
                                   for y, row in extra["calendar_years"].items()}
        return shown

    def comparison(window):
        need_returns()
        lookbacks = ctx.cfg.momentum.lookbacks
        if any(f"MOM{L}" not in ctx.returns.columns for L in lookbacks):
            raise ToolError("Momentum returns are missing. The Backtest Agent must run all lookbacks.")
        if window not in COMPARISON_WINDOWS:
            raise ToolError(f"Comparison windows are {list(COMPARISON_WINDOWS)}.")
        ctx.record("compute_comparison", window=window)
        result = comparison_window(ctx.returns, window, lookbacks)
        extras = comparison_extras(ctx.returns, lookbacks, ctx.cfg.strategy.cost_bps) if window == "S2011" else None
        with ctx.lock:
            ctx.analytics = ctx.analytics or {"windows": {}}
            comp = ctx.analytics.setdefault("comparison", {"windows": {}})
            comp["windows"][window] = result
            if extras:
                comp.update(extras)
        shown = display(result)
        if extras:
            shown["growth_of_10000"] = {k: f"${v:,.0f}" for k, v in extras["growth_of_10000"].items()}
            shown["calendar_years"] = {y: {k: f"{v * 100:.1f}%" for k, v in row.items()}
                                       for y, row in extras["calendar_years"].items()}
            shown["cost_sensitivity_if_charged_ma_costs"] = {
                k: {"turnover": round(v["turnover"], 2), "cagr_gross": f"{v['cagr_gross'] * 100:.1f}%",
                    "cagr_with_costs": f"{v['cagr_with_costs'] * 100:.1f}%"}
                for k, v in extras["cost_sensitivity"].items()}
        return shown

    def save(findings):
        missing = [w for w in WINDOWS if w not in (ctx.analytics or {}).get("windows", {})]
        if missing:
            raise ToolError(f"Compute every window first; missing {missing}.")
        if "rolling_1y" not in ctx.analytics:
            raise ToolError("Run rolling_analysis first.")
        missing_c = [w for w in COMPARISON_WINDOWS if w not in ctx.analytics.get("comparison", {}).get("windows", {})]
        if missing_c:
            raise ToolError(f"Compute every comparison window first; missing {missing_c}.")
        if not 5 <= len(findings) <= 9:
            raise ToolError("Provide 5 to 9 findings.")
        if sum("momentum" in f.lower() for f in findings) < 2:
            raise ToolError("At least two findings must be about the momentum sub-strategies.")
        if not any("qqq" in f.lower() for f in findings):
            raise ToolError("At least one finding must compare against the QQQ benchmark.")
        index = ctx.number_index()
        problems = [f"Finding {i + 1}: {p}" for i, f in enumerate(findings) for p in check_text(f, index)]
        if problems:
            raise ToolError("Findings rejected by guardrails:\n" + "\n".join(problems))
        ctx.record("save_analytics")
        ctx.analytics["findings"] = findings
        write_json(ctx.path("analytics.json"), ctx.analytics)
        return {"saved": "analytics.json", "findings": len(findings)}

    tools = [
        Tool("compute_metrics", "Metrics for Strategy, SPY and 60/40 over one trailing window: returns, volatility, "
             "Sharpe, Sortino, max drawdown, Calmar, beta, correlation, capture ratios, hit rate, switching activity.",
             schema({"window": {"type": "string", "enum": list(WINDOWS)}}, ["window"]), metrics),
        Tool("rolling_analysis", "Rolling 1-year comparison vs SPY, growth of $10,000, calendar-year returns.",
             schema(), rolling),
        Tool("compute_comparison", "Head-to-head metrics over one window of the common period since 2011: "
             "MOM1, MOM3, MOM6, MOM12, MOM24, the MA strategy, SPY and QQQ, plus momentum activity (rebalances, "
             "cash, current weights). S2011 also returns calendar years, growth of $10,000 and cost sensitivity.",
             schema({"window": {"type": "string", "enum": list(COMPARISON_WINDOWS)}}, ["window"]), comparison),
        Tool("save_analytics", "Save analytics with 5-9 one-sentence findings (at least 2 on momentum). Numbers are verified.",
             schema({"findings": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 9}},
                    ["findings"]), save),
    ]
    return Agent(ctx.client, "Analytics Agent", PROMPT, tools, ctx.trace, effort="medium",
                 max_turns=ctx.cfg.max_turns_per_agent, token_budget=ctx.cfg.token_budget, model=ctx.cfg.model)


def task(ctx):
    return (f"Analyze the strategy from {ctx.backtest['oos_start']} to {ctx.backtest['end']} "
            "across all windows and save your findings.")
