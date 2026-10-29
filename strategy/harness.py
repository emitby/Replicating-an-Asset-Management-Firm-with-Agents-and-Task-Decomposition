"""Pipeline orchestration.

    Team Agent ───────────────────────────────────────────────────────────────────────┐ (in parallel)
    Data → Research R1 → Portfolio Manager R1 → Research R2 → Portfolio Manager R2 → Analytics ┴→ Presentation

The harness is deterministic code, not an LLM. Each stage runs one agent, and
then a validator checks the stage's artifact. A failed check stops the run
with a clear error, so a later agent never builds on a bad input.

The Research and Portfolio Manager Agents alternate: the Research Agent runs
the 84-strategy grid; the PM selects the top 5 and proposes 5 new parameter
sets; the Research Agent runs them; the PM applies the replacement rule and
explains the final line-up. Their messages form `dialogue.json`.

The PDF is rendered from saved artifacts only (`strategy.pdf.build_from_run`),
so after a run it can be edited and rebuilt with ``build-pdf`` without re-running
any agent. The harness renders it one last time after writing the manifest, so
the deck's harness page shows the run's final cost per agent and per tool.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from strategy import __version__
from strategy.agents import analytics_agent, data_agent, pm_agent, presentation_agent, research_agent, team_agent
from strategy.agents.runtime import Trace, make_client
from strategy.config import UNIVERSE, WINDOWS, PipelineConfig
from strategy.context import RunContext
from strategy.guardrails import check_text
from strategy.hooks import CallCounter, default_hooks
from strategy.paths import new_run_dir, write_json, write_text
from strategy.ranking import apply_replacement, top_n


class StageError(RuntimeError):
    """A stage's artifact failed validation; the run stops."""


@dataclass
class Stage:
    """One pipeline step: build an agent, give it a task, then validate the result.

    Attributes:
        name: stage name (used in the CLI, trace and notes).
        build: ``ctx -> Agent``.
        task: ``ctx -> str``.
        validate: ``ctx -> None``; raises `StageError`.
    """
    name: str
    build: Callable
    task: Callable
    validate: Callable


def _require(cond, msg):
    """Raise `StageError(msg)` unless `cond`."""
    if not cond:
        raise StageError(msg)


def validate_data(ctx):
    """The dataset exists and covers every universe ETF plus ^IRX with no gaps."""
    _require(ctx.prices is not None and ctx.path("prices.csv").exists(), "Data Agent did not save a dataset.")
    _require({*UNIVERSE, "^IRX"} <= set(ctx.prices.columns), "Dataset is missing a ticker.")
    _require(ctx.prices[list(UNIVERSE)].notna().all().all(), "Dataset has missing ETF prices.")


def validate_research(round_):
    """Validator factory: the Research Agent ran and saved round `round_`."""
    def check(ctx):
        cfg = ctx.cfg.ranking
        _require(round_ in ctx.research and ctx.path("research.json").exists(), f"Research round {round_} not saved.")
        if round_ == 1:
            _require(len(ctx.research[1]["ids"]) == cfg.grid_size, "Round 1 did not cover the whole grid.")
        else:
            _require(set(ctx.research[2]["ids"]) == {p["id"] for p in ctx.pm["proposals"]}, "Round 2 missed a proposal.")
        _require(all(sid in ctx.scores.index for sid in ctx.research[round_]["ids"]), "A strategy was not scored.")
    return check


def validate_pm(round_):
    """Validator factory: the PM's decisions follow the rules computed in code."""
    def check(ctx):
        cfg = ctx.cfg.ranking
        if round_ == 1:
            _require([p["id"] for p in ctx.pm.get("top5", [])] == top_n(ctx.scores, cfg.top_n, ctx.research[1]["ids"]),
                     "PM top selection does not match the total-return ranking.")
            _require(len(ctx.pm.get("proposals", [])) == cfg.n_proposals, "PM did not propose every strategy.")
            _require(not {p["id"] for p in ctx.pm["proposals"]} & set(ctx.research[1]["ids"]), "A proposal repeats round 1.")
        else:
            final = ctx.pm.get("final")
            _require(final is not None, "PM did not finalize.")
            expected = apply_replacement(ctx.scores, [p["id"] for p in ctx.pm["top5"]], [p["id"] for p in ctx.pm["proposals"]])
            _require(final["final"] == expected["final"], "PM final line-up does not follow the replacement rule.")
            _require(bool(ctx.pm.get("meeting")), "PM did not write the meeting script.")
            _require(set(ctx.pm.get("feedback", {})) == {"constructive", "harsh"}, "PM did not write both feedback scripts.")
        _require(ctx.path("pm.json").exists(), "pm.json missing.")
    return check


def validate_analytics(ctx):
    """Analytics saved for every window, with portfolio fit and findings."""
    _require(ctx.analytics is not None and ctx.path("analytics.json").exists(), "Analytics Agent did not save.")
    _require(set(WINDOWS) <= set(ctx.analytics["windows"]), "Analytics missing a window.")
    _require("portfolio_fit" in ctx.analytics, "Portfolio fit missing.")
    _require(5 <= len(ctx.analytics.get("findings", [])) <= 9, "Analytics findings missing.")


def validate_team(ctx):
    """The fictional team has exactly six members."""
    _require(ctx.team is not None and len(ctx.team["members"]) == 6, "Team Agent did not produce a valid team.")


def validate_presentation(ctx):
    """The PDF exists, and every agent-written string in the deck passes the guardrails again."""
    _require(ctx.path("presentation.pdf").exists() and ctx.path("deck.json").exists(),
             "Presentation Agent did not build the deck.")
    index = ctx.number_index()
    problems = []
    for s in ctx.slides:
        problems += [f"{s['title']!r}: {p}" for p in check_text(" \n".join([s["title"], *s["bullets"]]), index)]
    _require(not problems, "Final guardrail check failed:\n" + "\n".join(problems))


def _stage(name, module, validate, round_=None):
    """A `Stage` for an agent module, binding the research round when the agent has two."""
    if round_ is None:
        return Stage(name, module.build, module.task, validate)
    return Stage(name, lambda ctx: module.build(ctx, round_), lambda ctx: module.task(ctx, round_), validate)


STAGES = {
    "data": _stage("data", data_agent, validate_data),
    "research1": _stage("research1", research_agent, validate_research(1), 1),
    "pm1": _stage("pm1", pm_agent, validate_pm(1), 1),
    "research2": _stage("research2", research_agent, validate_research(2), 2),
    "pm2": _stage("pm2", pm_agent, validate_pm(2), 2),
    "analytics": _stage("analytics", analytics_agent, validate_analytics),
    "team": _stage("team", team_agent, validate_team),
    "presentation": _stage("presentation", presentation_agent, validate_presentation),
}
SEQUENCE = ("data", "research1", "pm1", "research2", "pm2", "analytics")


def run_stage(ctx, name):
    """Run one stage: build the agent, run its task, validate, and save the agent's reply.

    Raises:
        StageError: the stage's artifact failed validation.
        AgentError: the agent failed (turn limit, token budget).
    """
    stage = STAGES[name]
    t0 = time.perf_counter()
    ctx.trace.log(agent="harness", type="stage_start", stage=name)
    agent = stage.build(ctx)
    ctx.notes[name] = agent.run(stage.task(ctx))
    stage.validate(ctx)
    write_text(ctx.path("notes", f"{name}.md"), ctx.notes[name] + "\n")
    if name in ("pm1", "pm2", "research1", "research2"):
        write_json(ctx.path("dialogue.json"), ctx.dialogue)
    ctx.trace.log(agent="harness", type="stage_ok", stage=name, seconds=round(time.perf_counter() - t0, 1))


def new_context(cfg=None, label=None, client=None):
    """A fresh run folder and context, with the default tool hooks installed."""
    cfg = cfg or PipelineConfig()
    run_dir = new_run_dir(label)
    return RunContext(run_dir=run_dir, cfg=cfg, trace=Trace(run_dir / "trace.jsonl"), client=client or make_client(),
                      hooks=default_hooks())


def run_pipeline(ctx):
    """Run every stage in order (the Team Agent in parallel), then write the manifest and final PDF.

    Returns:
        The context. Re-raises the first failure after writing a 'failed' manifest.
    """
    t0 = time.perf_counter()
    status, error = "ok", None
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            team_future = pool.submit(run_stage, ctx, "team")      # independent of the data
            for name in SEQUENCE:
                run_stage(ctx, name)
            team_future.result()
        run_stage(ctx, "presentation")
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        ctx.trace.log(agent="harness", type="run_failed", error=error)
        raise
    finally:
        write_manifest(ctx, status, error, time.perf_counter() - t0)
    _final_render(ctx)
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
    if name == "presentation":
        _final_render(ctx)
    return ctx


def _final_render(ctx):
    """Re-render the presentation from the saved artifacts, now that the manifest has the run's full cost,
    and build the pitchbook (its appendix reuses the presentation's pages)."""
    from strategy.pdf import build_from_run
    from strategy.pitchbook import build_pitchbook_from_run
    build_from_run(ctx.run_dir)
    build_pitchbook_from_run(ctx.run_dir)


def write_manifest(ctx, status, error, seconds, **extra):
    """Write manifest.json: status, versions, data facts, tokens and cost (total, per agent, per tool), hooks."""
    counter = next((h for h in (ctx.hooks.post if ctx.hooks else []) if isinstance(h, CallCounter)), None)
    events = ctx.trace.events()
    write_json(ctx.path("manifest.json"), {
        "status": status, "error": error, "version": __version__, "model": ctx.cfg.model,
        "strategy_params": ctx.cfg.ranking.to_dict(), "offline": ctx.cfg.offline,
        "data_hash": (ctx.data_report or {}).get("sha256_16"),
        "data_range": [(ctx.data_report or {}).get("cleaned_start"), (ctx.data_report or {}).get("cleaned_end")],
        "seconds": round(seconds, 1), "usage_tokens": ctx.trace.usage, "cost_usd": ctx.trace.cost_usd(),
        "cost_by_agent_usd": {a: ctx.trace.cost_usd(u) for a, u in ctx.trace.by_agent.items()},
        "tokens_by_agent": ctx.trace.by_agent,
        "cost_by_tool": ctx.trace.tool_report(),
        "tool_calls": counter.counts if counter else {},
        "hooks": {"pre": [h.__name__ for h in ctx.hooks.pre], "post": [getattr(h, "__name__", "hook") for h in ctx.hooks.post],
                  "denials": [e for e in events if e.get("type") == "hook_denied"]} if ctx.hooks else None,
        "final_strategies": (ctx.pm.get("final") or {}).get("final"),
        "artifacts": sorted(p.name for p in ctx.run_dir.iterdir() if p.is_file()),
        **extra,
    })
