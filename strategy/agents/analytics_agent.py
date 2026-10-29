"""Analytics Agent: risk, return and portfolio fit of the Portfolio Manager's final strategies.

Runs after the Portfolio Manager Agent's final decision. Code computes every
metric (`strategy.analytics`); the agent chooses what to examine and writes the
findings an investment committee reads. Findings are guardrail-checked on save.
"""

from strategy.agents import views
from strategy.agents.display import display
from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.analytics import calendar_year_returns, compute_window, growth_of, portfolio_fit, report_series
from strategy.config import WINDOWS
from strategy.guardrails import check_text
from strategy.paths import write_json
from strategy.ranking import rule_text

PROMPT = """You are the Analytics Agent at Agentic Capital Management, an AI-run research pipeline. The Portfolio Manager Agent has chosen {top} final strategies from a month-end ETF ranking family. The rule: {rule}

Your job:
1. Compute metrics for the final strategies, SPY and QQQ over every window: {windows} (SI = the whole common backtest window). 1Y shows the one-year total return.
2. Run calendar_and_growth: calendar-year returns and the growth of $10,000.
3. Run portfolio_fit: each final strategy's correlation with SPY, QQQ, TLT and GLD, and a blend of {spy_w}% SPY + {strat_w}% strategy against SPY alone.
4. Save 5 to 9 findings: one sentence each, specific and balanced. Cover returns against SPY and QQQ, risk (drawdowns, volatility), how results vary by period, and at least one finding on how the strategies could fit in a diversified portfolio (correlation or the blend). An investment committee will read them.

Rules: quote numbers exactly as the tools display them (percentages to 1 decimal, ratios to 2), or rounded further. Never compute new numbers yourself: no differences, averages or ratios that a tool didn't return. Saving checks every number and rejects any it can't find in the results. Don't promise future returns."""


def build(ctx):
    """Build the Analytics Agent.

    Args:
        ctx: the run context (needs the PM's final decision and the strategy returns).

    Returns:
        A configured `Agent`.
    """
    cfg = ctx.cfg.ranking

    def final_ids():
        if "final" not in ctx.pm:
            raise ToolError("The Portfolio Manager Agent has not made its final decision yet.")
        return ctx.pm["final"]["final"]

    def labels():
        return {sid: ctx.specs[sid].label for sid in final_ids()}

    def ensure():
        with ctx.lock:
            ctx.analytics = ctx.analytics or {"series": report_series(final_ids()), "labels": labels(), "windows": {}}

    def metrics(window):
        series = report_series(final_ids())
        if window not in WINDOWS:
            raise ToolError(f"Windows are {list(WINDOWS)}.")
        ctx.record("compute_metrics", window=window)
        result = compute_window(ctx.returns, window, series)
        ensure()
        with ctx.lock:
            ctx.analytics["windows"][window] = result
        return {"labels": labels(), **display(result)}

    def calendar_and_growth():
        series = report_series(final_ids())
        ctx.record("calendar_and_growth")
        extra = {"growth_of_10000": growth_of(ctx.returns, series),
                 "calendar_years": calendar_year_returns(ctx.returns, series)}
        ensure()
        with ctx.lock:
            ctx.analytics.update(extra)
        last_year = max(extra["calendar_years"])
        return {"labels": labels(), "note": f"{last_year} is year-to-date (YTD).",
                "growth_of_10000": {k: f"${v:,.0f}" for k, v in extra["growth_of_10000"].items()},
                "calendar_years": {y: {k: f"{v * 100:.1f}%" for k, v in row.items()}
                                   for y, row in extra["calendar_years"].items()}}

    def fit():
        ids = final_ids()
        ctx.record("portfolio_fit")
        result = portfolio_fit(ctx.returns, ctx.prices, ids, cfg.blend_weight)
        ensure()
        with ctx.lock:
            ctx.analytics["portfolio_fit"] = result
        keep = ("total_return", "cagr", "volatility", "max_drawdown", "sharpe", "correlation", "beta")
        return {"labels": labels(), "blend": f"{100 - round(cfg.blend_weight * 100)}% SPY + "
                f"{round(cfg.blend_weight * 100)}% strategy, rebalanced daily",
                "correlation": {sid: {a: f"{v:.2f}" for a, v in row.items()} for sid, row in result["correlation"].items()},
                "blends": {sid: display({k: v for k, v in m.items() if k in keep}) for sid, m in result["blends"].items()},
                "spy_alone": display({k: v for k, v in result["spy"].items() if k in keep})}

    def save(findings):
        missing = [w for w in WINDOWS if w not in (ctx.analytics or {}).get("windows", {})]
        if missing:
            raise ToolError(f"Compute every window first; missing {missing}.")
        for key, tool in (("calendar_years", "calendar_and_growth"), ("portfolio_fit", "portfolio_fit")):
            if key not in ctx.analytics:
                raise ToolError(f"Run {tool} first.")
        if not 5 <= len(findings) <= 9:
            raise ToolError("Provide 5 to 9 findings.")
        if not any(w in f.lower() for f in findings for w in ("correlat", "blend", "diversif")):
            raise ToolError("At least one finding must cover portfolio fit (correlation or the blend).")
        if not any("drawdown" in f.lower() for f in findings):
            raise ToolError("At least one finding must cover drawdowns.")
        index = ctx.number_index()
        problems = [f"Finding {i + 1}: {p}" for i, f in enumerate(findings) for p in check_text(f, index)]
        if problems:
            raise ToolError("Findings rejected by guardrails:\n" + "\n".join(problems))
        ctx.record("save_analytics")
        ctx.analytics["findings"] = findings
        write_json(ctx.path("analytics.json"), ctx.analytics)
        return {"saved": "analytics.json", "findings": len(findings)}

    tools = [
        Tool("compute_metrics", "Metrics for the final strategies, SPY and QQQ over one trailing window: returns, "
             "volatility, Sharpe, Sortino, max drawdown, Calmar, beta, correlation, capture ratios, hit rate.",
             schema({"window": {"type": "string", "enum": list(WINDOWS)}}, ["window"]), metrics),
        Tool("calendar_and_growth", "Calendar-year returns and the growth of $10,000 for the final strategies, SPY and QQQ.",
             schema(), calendar_and_growth),
        Tool("portfolio_fit", "Correlations with SPY, QQQ, TLT and GLD, and a SPY + strategy blend vs SPY alone.",
             schema(), fit),
        Tool("save_analytics", "Save analytics with 5-9 one-sentence findings. Numbers are verified.",
             schema({"findings": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 9}},
                    ["findings"]), save),
    ]
    prompt = PROMPT.format(top=cfg.top_n, rule=rule_text(cfg), windows=", ".join(WINDOWS),
                           spy_w=100 - round(cfg.blend_weight * 100), strat_w=round(cfg.blend_weight * 100))
    return Agent(ctx.client, "Analytics Agent", prompt, tools, ctx.trace, effort="medium",
                 max_turns=ctx.cfg.max_turns_per_agent, token_budget=ctx.cfg.token_budget, model=ctx.cfg.model,
                 hooks=ctx.hooks)


def task(ctx):
    """The Analytics Agent's task message."""
    final = ", ".join(f"{sid} ({ctx.specs[sid].label})" for sid in ctx.pm["final"]["final"])
    return f"Analyze the final strategies over {views.window(ctx)}: {final}. Save your findings."
