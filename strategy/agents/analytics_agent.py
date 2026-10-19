"""Analytics Agent: performance and risk over 3M, 1Y, 3Y, 5Y and since inception."""

from strategy.agents.display import display
from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.analytics import calendar_year_returns, compute_window, growth_of, rolling_summary
from strategy.config import WINDOWS
from strategy.guardrails import check_text
from strategy.paths import write_json

PROMPT = """You are the Analytics Agent in an investment research pipeline. You analyze the out-of-sample performance of a strategy that switches between SPY and IEF on a walk-forward-selected moving average. You compare it with SPY buy-and-hold and a 60/40 SPY/IEF mix.

Your job:
1. Compute metrics for every window: 3M, 1Y, 3Y, 5Y and SI (since the walk-forward start). 3M shows total returns only. Longer windows are annualized.
2. Run the rolling and calendar-year analysis.
3. Save 4 to 7 findings: one sentence each, specific and balanced. Cover where the strategy helped (e.g. drawdowns, crisis years), where it lagged (e.g. strong bull markets, choppy markets), and risk-adjusted results. An investment committee will read them.

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

    def save(findings):
        missing = [w for w in WINDOWS if w not in (ctx.analytics or {}).get("windows", {})]
        if missing:
            raise ToolError(f"Compute every window first; missing {missing}.")
        if "rolling_1y" not in ctx.analytics:
            raise ToolError("Run rolling_analysis first.")
        if not 4 <= len(findings) <= 7:
            raise ToolError("Provide 4 to 7 findings.")
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
        Tool("save_analytics", "Save analytics with 4-7 one-sentence findings. Numbers are verified.",
             schema({"findings": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 7}},
                    ["findings"]), save),
    ]
    return Agent(ctx.client, "Analytics Agent", PROMPT, tools, ctx.trace, effort="medium",
                 max_turns=ctx.cfg.max_turns_per_agent, token_budget=ctx.cfg.token_budget, model=ctx.cfg.model)


def task(ctx):
    return (f"Analyze the strategy from {ctx.backtest['oos_start']} to {ctx.backtest['end']} "
            "across all windows and save your findings.")
