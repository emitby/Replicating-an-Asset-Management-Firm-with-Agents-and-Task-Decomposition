"""Backtest Agent: runs every moving-average candidate and the walk-forward selection."""

from strategy.agents.display import display
from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.analytics import series_metrics
from strategy.backtest import candidate_table, common_start, daily_rf, run_all, run_ma_backtest
from strategy.paths import write_json, write_text

PROMPT = """You are the Backtest Agent in an investment research pipeline. The strategy holds 100% SPY when SPY closed above its N-day simple moving average the previous day, and 100% IEF otherwise. The candidates are N = {windows}. Each switch costs {cost} bps.

Your job:
1. Backtest every candidate moving average individually (run_ma_backtest for each N).
2. Run the walk-forward selection. Each January it picks the candidate with the best Sharpe ratio using only prior data (expanding window, minimum {min_train} years), and trades it for that year. This is the strategy's official, out-of-sample result.
3. Compare the candidates (compare_candidates). This is IN-SAMPLE, hindsight context only.
4. Save the backtest with a short methodology summary.
5. Reply with a brief note: which MAs the walk-forward chose and how often, the current allocation, and any caveats. Examples: in-sample vs out-of-sample differences, sensitivity to the MA choice, switching frequency.

Rules: the official strategy is the walk-forward result. Never present the best in-sample candidate as the strategy. Quote only numbers the tools return, as given."""


def build(ctx):
    cfg = ctx.cfg.strategy

    def need_prices():
        if ctx.prices is None:
            raise ToolError("No dataset loaded. The Data Agent must save one first.")

    def ma_backtest(ma_days):
        need_prices()
        if ma_days not in cfg.ma_windows:
            raise ToolError(f"Candidates are {list(cfg.ma_windows)}.")
        ctx.record("run_ma_backtest", ma_days=ma_days)
        start = common_start(ctx.prices, cfg.ma_windows)
        w, r = run_ma_backtest(ctx.prices, ma_days, cfg.cost_bps, start)
        m = series_metrics(r, daily_rf(ctx.prices), annualize=True)
        m["switches"] = int(w.diff().abs().fillna(0).gt(0).sum())
        m["pct_time_in_spy"] = float(w.mean())
        return {"ma_days": ma_days, "period": f"{start.date()} to {r.index.max().date()}",
                "note": "IN-SAMPLE full-period result for this single rule", "metrics": display(m)}

    def walk_forward(min_train_years=cfg.min_train_years):
        need_prices()
        if min_train_years != cfg.min_train_years:
            raise ToolError(f"min_train_years is fixed at {cfg.min_train_years} by the strategy configuration.")
        ctx.record("run_walk_forward", min_train_years=min_train_years)
        ctx.wf, ctx.returns = run_all(ctx.prices, cfg)
        hist = ctx.wf["selection_history"]
        counts = {}
        for h in hist:
            counts[f"MA{h['chosen_ma']}"] = counts.get(f"MA{h['chosen_ma']}", 0) + 1
        return {"oos_start": str(ctx.wf["oos_start"].date()), "years_selected": len(hist),
                "times_chosen": counts,
                "recent_choices": [{"year": h["year"], "chosen_ma": h["chosen_ma"]} for h in hist[-6:]],
                "current_allocation_spy": display(float(ctx.returns["w_spy"].iloc[-1]), "current_allocation_spy")}

    def compare():
        if ctx.wf is None:
            raise ToolError("Run the walk-forward first: the comparison uses the same out-of-sample period.")
        ctx.record("compare_candidates")
        ctx.candidates = candidate_table(ctx.prices, ctx.wf, daily_rf(ctx.prices))
        return {"note": "IN-SAMPLE: uses hindsight; context only", "candidates": display(ctx.candidates)}

    def save(methodology_summary):
        done = {c["ma_days"] for c in ctx.calls.get("run_ma_backtest", [])}
        missing = [n for n in cfg.ma_windows if n not in done]
        if missing:
            raise ToolError(f"Backtest every candidate first; missing MA {missing}.")
        if ctx.wf is None or ctx.candidates is None:
            raise ToolError("Run the walk-forward and compare_candidates before saving.")
        ctx.record("save_backtest")
        hist = ctx.wf["selection_history"]
        ctx.backtest = {
            "params": cfg.to_dict(), "oos_start": str(ctx.wf["oos_start"].date()),
            "common_start": str(ctx.wf["common_start"].date()), "end": str(ctx.returns.index.max().date()),
            "selection_history": hist, "candidates_in_sample": ctx.candidates,
            "years_selected": len(hist), "current_allocation_spy": float(ctx.returns["w_spy"].iloc[-1]),
            "methodology_summary": methodology_summary,
        }
        write_json(ctx.path("backtest.json"), ctx.backtest)
        write_text(ctx.path("returns.csv"), ctx.returns.to_csv())
        return {"saved": ["backtest.json", "returns.csv"], "rows": len(ctx.returns)}

    tools = [
        Tool("run_ma_backtest", "Backtest one single-MA switching rule over the full period (in-sample).",
             schema({"ma_days": {"type": "integer", "enum": list(cfg.ma_windows)}}, ["ma_days"]), ma_backtest),
        Tool("run_walk_forward", "Run the walk-forward MA selection: the strategy's official out-of-sample result.",
             schema({"min_train_years": {"type": "integer"}}), walk_forward),
        Tool("compare_candidates", "In-sample comparison table of all candidates over the walk-forward period.",
             schema(), compare),
        Tool("save_backtest", "Save the backtest results with a methodology summary (2-4 sentences).",
             schema({"methodology_summary": {"type": "string"}}, ["methodology_summary"]), save),
    ]
    prompt = PROMPT.format(windows=list(cfg.ma_windows), cost=cfg.cost_bps, min_train=cfg.min_train_years)
    return Agent(ctx.client, "Backtest Agent", prompt, tools, ctx.trace, effort="low",
                 max_turns=ctx.cfg.max_turns_per_agent, token_budget=ctx.cfg.token_budget, model=ctx.cfg.model)


def task(ctx):
    return (f"The dataset runs from {ctx.prices.index.min().date()} to {ctx.prices.index.max().date()}. "
            "Run the full backtest and save it.")
