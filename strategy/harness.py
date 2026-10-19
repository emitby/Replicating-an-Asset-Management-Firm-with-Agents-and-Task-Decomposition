"""Pipeline orchestration.

    Team Agent ─────────────────────────────────────────────┐ (runs in parallel)
    Data Agent → Backtest Agent → Analytics Agent ──────────┴→ Presentation Agent → final checks

The harness is deterministic code, not an LLM. Each stage runs one agent, and
then a validator checks the stage's artifact. A failed check stops the run
with a clear error, so a later agent never builds on a bad input.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from strategy import __version__
from strategy.agents import analytics_agent, backtest_agent, data_agent, presentation_agent, team_agent
from strategy.agents.runtime import Trace, make_client
from strategy.config import WINDOWS, PipelineConfig
from strategy.context import RunContext
from strategy.guardrails import check_text
from strategy.paths import new_run_dir, write_json, write_text


class StageError(RuntimeError):
    pass


@dataclass
class Stage:
    name: str
    module: object
    validate: Callable


def _require(cond, msg):
    if not cond:
        raise StageError(msg)


def validate_data(ctx):
    _require(ctx.prices is not None and ctx.path("prices.csv").exists(), "Data Agent did not save a dataset.")
    _require({"SPY", "IEF", "^IRX"} <= set(ctx.prices.columns), "Dataset is missing a ticker.")
    _require(ctx.prices[["SPY", "IEF"]].notna().all().all(), "Dataset has missing ETF prices.")


def validate_backtest(ctx):
    _require(ctx.backtest is not None and ctx.path("backtest.json").exists(), "Backtest Agent did not save.")
    ran = {c["ma_days"] for c in ctx.calls.get("run_ma_backtest", [])}
    _require(set(ctx.cfg.strategy.ma_windows) <= ran, f"Not every MA was backtested: {sorted(ran)}.")
    _require(ctx.backtest["years_selected"] >= 5, "Walk-forward produced too few years.")


def validate_analytics(ctx):
    _require(ctx.analytics is not None and ctx.path("analytics.json").exists(), "Analytics Agent did not save.")
    _require(set(WINDOWS) <= set(ctx.analytics["windows"]), "Analytics missing a window.")
    _require(4 <= len(ctx.analytics.get("findings", [])) <= 7, "Analytics findings missing.")


def validate_team(ctx):
    _require(ctx.team is not None and len(ctx.team["members"]) == 6, "Team Agent did not produce a valid team.")


def validate_presentation(ctx):
    _require(ctx.path("presentation.pdf").exists(), "Presentation Agent did not build the PDF.")
    # Defense in depth: re-check every agent-written string that reached the PDF.
    index = ctx.number_index()
    problems = []
    for s in ctx.slides:
        if s["type"] == "slide":
            problems += [f"{s['title']!r}: {p}" for p in check_text(" \n".join([s["title"], *s["bullets"]]), index)]
    _require(not problems, "Final guardrail check failed:\n" + "\n".join(problems))


STAGES = {
    "data": Stage("data", data_agent, validate_data),
    "backtest": Stage("backtest", backtest_agent, validate_backtest),
    "analytics": Stage("analytics", analytics_agent, validate_analytics),
    "team": Stage("team", team_agent, validate_team),
    "presentation": Stage("presentation", presentation_agent, validate_presentation),
}


def run_stage(ctx, name):
    stage = STAGES[name]
    t0 = time.perf_counter()
    ctx.trace.log(agent="harness", type="stage_start", stage=name)
    agent = stage.module.build(ctx)
    ctx.notes[name] = agent.run(stage.module.task(ctx))
    stage.validate(ctx)
    write_text(ctx.path("notes", f"{name}.md"), ctx.notes[name] + "\n")
    ctx.trace.log(agent="harness", type="stage_ok", stage=name, seconds=round(time.perf_counter() - t0, 1))


def new_context(cfg=None, label=None, client=None):
    cfg = cfg or PipelineConfig()
    run_dir = new_run_dir(label)
    return RunContext(run_dir=run_dir, cfg=cfg, trace=Trace(run_dir / "trace.jsonl"), client=client or make_client())


def run_pipeline(ctx):
    t0 = time.perf_counter()
    status, error = "ok", None
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            team_future = pool.submit(run_stage, ctx, "team")      # independent of the data
            for name in ("data", "backtest", "analytics"):
                run_stage(ctx, name)
            team_future.result()
        run_stage(ctx, "presentation")
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        ctx.trace.log(agent="harness", type="run_failed", error=error)
        raise
    finally:
        write_manifest(ctx, status, error, time.perf_counter() - t0)
    return ctx


def rerun_stage(ctx, name, source_run):
    """Re-run one stage using artifacts saved by an earlier run."""
    ctx.load_artifacts(source_run)
    t0 = time.perf_counter()
    status, error = "ok", None
    try:
        run_stage(ctx, name)
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        write_manifest(ctx, status, error, time.perf_counter() - t0, source_run=str(source_run), stage=name)
    return ctx


def write_manifest(ctx, status, error, seconds, **extra):
    write_json(ctx.path("manifest.json"), {
        "status": status, "error": error, "version": __version__, "model": ctx.cfg.model,
        "strategy_params": ctx.cfg.strategy.to_dict(), "offline": ctx.cfg.offline,
        "data_hash": (ctx.data_report or {}).get("sha256_16"),
        "data_range": [(ctx.data_report or {}).get("cleaned_start"), (ctx.data_report or {}).get("cleaned_end")],
        "seconds": round(seconds, 1), "usage_tokens": ctx.trace.usage, "cost_usd": ctx.trace.cost_usd(),
        "cost_by_agent_usd": {a: ctx.trace.cost_usd(u) for a, u in ctx.trace.by_agent.items()},
        "artifacts": sorted(p.name for p in ctx.run_dir.iterdir() if p.is_file()),
        **extra,
    })
