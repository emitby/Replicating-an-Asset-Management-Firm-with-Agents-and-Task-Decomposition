"""Agent and harness tests with scripted Claude clients: no API calls.

The end-to-end tests use the shared `offline_run` fixture (all six agents through the real harness);
the protocol tests call the Research and PM tools directly to probe each rule.
"""

import pytest

from conftest import FakeClaude, response, text, tool_use
from fixtures import VALID_TEAM
from strategy.agents import (analytics_agent, data_agent, pm_agent, presentation_agent, research_agent, team_agent,
                             views)
from strategy.agents.runtime import AgentError, BudgetExceeded, ToolError, Trace
from strategy.config import PipelineConfig
from strategy.context import RunContext
from strategy.harness import run_stage
from strategy.hooks import default_hooks
from strategy.ranking import common_start, grid, run_strategy, top_n


def make_ctx(workdir, client=None, prices=None, **cfg):
    ctx = RunContext(run_dir=workdir, cfg=PipelineConfig(**cfg), trace=Trace(workdir / "trace.jsonl"), client=client,
                     hooks=default_hooks())
    ctx.prices = prices
    return ctx


def tool(ctx, module, name, round_=None):
    """A tool handler of a freshly built agent (round-aware)."""
    agent = module.build(ctx) if round_ is None else module.build(ctx, round_)
    return agent.tools[name].handler


@pytest.fixture
def round1_ctx(workdir, prices):
    """A context after the Research Agent's round 1 (grid run and saved)."""
    ctx = make_ctx(workdir, prices=prices)
    tool(ctx, research_agent, "run_grid", 1)()
    tool(ctx, research_agent, "save_research", 1)(
        round=1, message_to_pm="Done.", findings=["Pro: a.", "Pro: b.", "Con: c.", "Con: d."])
    return ctx


# ------------------------------------------------------------------ end to end

def test_pipeline_runs_every_stage_and_writes_every_artifact(offline_run):
    ctx = offline_run
    for name in ("prices.csv", "research.json", "strategy_returns.csv", "pm.json", "dialogue.json", "analytics.json",
                 "team.json", "deck.json", "presentation.pdf", "manifest.json", "trace.jsonl"):
        assert ctx.path(name).exists(), name
    assert {e["agent"] for e in ctx.trace.events() if e.get("type") == "finish"} >= {
        "Data Agent", "Research Agent", "Portfolio Manager Agent", "Analytics Agent", "Team Agent", "Presentation Agent"}


def test_pm_loop_follows_the_rules(offline_run):
    ctx = offline_run
    assert [p["id"] for p in ctx.pm["top5"]] == top_n(ctx.scores, 5, ctx.research[1]["ids"])
    assert len(ctx.pm["proposals"]) == 5
    assert len(ctx.pm["final"]["final"]) == 5
    assert [d["from"] for d in ctx.dialogue] == ["Research Agent", "Portfolio Manager Agent", "Research Agent",
                                                 "Portfolio Manager Agent"]


def test_all_strategies_scored_on_identical_dates(offline_run):
    ctx = offline_run
    ids = [c for c in ctx.returns.columns if c in ctx.specs]
    assert len(ids) == 89
    assert ctx.returns[ids].notna().all().all()


# ------------------------------------------------------------------ Research Agent

def test_research_round1_tools(round1_ctx):
    ctx = round1_ctx
    assert len(ctx.research[1]["ids"]) == 84
    assert ctx.window_start == common_start({s.id: run_strategy(ctx.prices[list(ctx.cfg.ranking.universe)], s)[0]
                                             for s in grid(ctx.cfg.ranking)})
    detail = tool(ctx, research_agent, "strategy_detail", 1)(id="T1-SMA20-15d")
    assert set(detail["share_of_months_each_etf_led"]) <= set(ctx.cfg.ranking.universe)
    assert "T1-SMA20-15d" in ctx.facts["leader_share"]


def test_research_findings_need_pros_cons_and_real_numbers(workdir, prices):
    ctx = make_ctx(workdir, prices=prices)
    tool(ctx, research_agent, "run_grid", 1)()
    save = tool(ctx, research_agent, "save_research", 1)
    with pytest.raises(ToolError, match="Pro:"):
        save(round=1, message_to_pm="x", findings=["a", "b", "c", "d"])
    with pytest.raises(ToolError, match="not found"):
        save(round=1, message_to_pm="It returned 987.6%.", findings=["Pro: a.", "Pro: b.", "Con: c.", "Con: d."])


def test_research_round2_only_runs_pm_proposals(round1_ctx):
    ctx = round1_ctx
    ids = top_n(ctx.scores, 5, ctx.research[1]["ids"])
    tool(ctx, pm_agent, "get_results", 1)(round=1)
    tool(ctx, pm_agent, "select_top5", 1)(picks=[{"id": i, "rationale": "r.", "pro": "p.", "con": "c."} for i in ids])
    props = [{"portfolio": "Top 1", "sma": s, "lookback_days": d, "hypothesis": "h.", "pro": "p.", "con": "c."}
             for s, d in ((20, 10), (10, 15), (30, 20), (40, 25), (60, 45))]
    tool(ctx, pm_agent, "propose_strategies", 1)(proposals=props, message_to_research="Run these.")
    run = tool(ctx, research_agent, "run_strategy", 2)
    with pytest.raises(ToolError, match="not one of"):
        run(portfolio="Top 3 mix", sma=20, lookback_days=10)
    out = run(portfolio="Top 1", sma=20, lookback_days=10)
    assert out["id"] == "T1-SMA20-10d" and "beats_weakest_top" in out
    with pytest.raises(ToolError, match="Run every proposal"):
        tool(ctx, research_agent, "save_research", 2)(round=2, message_to_pm="x",
                                                       findings=["Pro: a.", "Pro: b.", "Con: c.", "Con: d."])


# ------------------------------------------------------------------ Portfolio Manager Agent

def test_pm_must_pick_the_true_top5(round1_ctx):
    ctx = round1_ctx
    tool(ctx, pm_agent, "get_results", 1)(round=1)
    wrong = top_n(ctx.scores, 6, ctx.research[1]["ids"])[1:]
    with pytest.raises(ToolError, match="not"):
        tool(ctx, pm_agent, "select_top5", 1)(picks=[{"id": i, "rationale": "r.", "pro": "p.", "con": "c."} for i in wrong])


def test_pm_proposals_validated(round1_ctx):
    ctx = round1_ctx
    tool(ctx, pm_agent, "get_results", 1)(round=1)
    ids = top_n(ctx.scores, 5, ctx.research[1]["ids"])
    tool(ctx, pm_agent, "select_top5", 1)(picks=[{"id": i, "rationale": "r.", "pro": "p.", "con": "c."} for i in ids])
    propose = tool(ctx, pm_agent, "propose_strategies", 1)

    def props(*specs):
        return [{"portfolio": p, "sma": s, "lookback_days": d, "hypothesis": "h.", "pro": "p.", "con": "c."}
                for p, s, d in specs]
    ok = [("Top 1", 20, 10), ("Top 1", 10, 15), ("Top 1", 30, 20), ("Top 1", 40, 25)]
    with pytest.raises(ToolError, match="already run"):
        propose(proposals=props(*ok, ("Top 1", 20, 15)), message_to_research="x")
    with pytest.raises(ToolError, match="more history"):
        propose(proposals=props(*ok, ("Top 1", 250, 365)), message_to_research="x")
    with pytest.raises(ToolError, match="exactly 5"):
        propose(proposals=props(*ok), message_to_research="x")
    # a proposal may cite its own parameters ("a 40-day SMA over 25 days"), but not invented statistics
    with pytest.raises(ToolError, match="not found"):
        propose(proposals=props(*ok, ("Top 1", 60, 45)), message_to_research="These should return 54.3%.")
    assert propose(proposals=props(*ok, ("Top 1", 60, 45)), message_to_research="Try a 60-day SMA over 45 days.")


def test_meeting_rules(offline_run):
    ctx = offline_run
    write = tool(ctx, pm_agent, "write_meeting", 2)
    good = ctx.pm["meeting"]
    with pytest.raises(ToolError, match="lines"):
        write(lines=good[:5])
    with pytest.raises(ToolError, match="at least twice"):
        write(lines=[{"speaker": "Portfolio Manager Agent", "text": line["text"]} for line in good])
    with pytest.raises(ToolError, match="cover"):
        write(lines=[{**line, "text": "We met."} for line in good])
    write(lines=good)


def test_feedback_rules(offline_run):
    """User request: a constructive page (correlation, returns, macro basket) and a harsh page built on real cons."""
    ctx = offline_run
    write = tool(ctx, pm_agent, "write_feedback", 2)
    good = ctx.pm["feedback"]
    with pytest.raises(ToolError, match="must cover"):
        write(constructive=[{**line, "text": "Nice work."} for line in good["constructive"]], harsh=good["harsh"])
    with pytest.raises(ToolError, match="real cons"):
        write(constructive=good["constructive"], harsh=[{**line, "text": "You are sloppy."} for line in good["harsh"]])
    with pytest.raises(ToolError, match="lines"):
        write(constructive=good["constructive"][:3], harsh=good["harsh"])
    with pytest.raises(ToolError, match="not found"):
        write(constructive=good["constructive"], harsh=[*good["harsh"][:-1],
                                                        {"speaker": "Research Agent", "text": "We lost 99.9% of it."}])
    write(constructive=good["constructive"], harsh=good["harsh"])


# ------------------------------------------------------------------ runtime

def test_team_agent_retries_after_validation_error(workdir):
    bad = [dict(m) for m in VALID_TEAM]
    bad[1] = dict(bad[1], experience=[{"firm": "BlackRock", "title": "VP", "years": "2010-2014"}])
    client = FakeClaude(
        response(tool_use("t1", "submit_team", members=bad), stop="tool_use"),
        response(tool_use("t2", "submit_team", members=VALID_TEAM), stop="tool_use"),
        response(text("Team accepted.")),
    )
    ctx = make_ctx(workdir, client)
    run_stage(ctx, "team")
    assert "real firm" in client.requests[1]["messages"][-1]["content"][0]["content"]
    assert len(ctx.team["members"]) == 6 and ctx.path("team.json").exists()


def test_turn_limit_and_budget(workdir):
    loop = [response(tool_use(f"x{i}", "submit_team", members=[]), stop="tool_use") for i in range(10)]
    ctx = make_ctx(workdir, FakeClaude(*loop))
    with pytest.raises(AgentError):
        team_agent.build(ctx).run("go")
    ctx = make_ctx(workdir, FakeClaude(*loop), token_budget=150)
    with pytest.raises(BudgetExceeded):
        team_agent.build(ctx).run("go")


def test_trace_and_cost(workdir):
    ctx = make_ctx(workdir, FakeClaude(response(text("hi"))))
    team_agent.build(ctx).run("go")
    types = [e["type"] for e in ctx.trace.events()]
    assert types == ["start", "model", "finish"]
    assert ctx.trace.cost_usd() == pytest.approx((100 * 4 + 20 * 20) / 1e6)


def test_all_agents_use_the_configured_model_and_hooks(workdir, prices):
    ctx = make_ctx(workdir, prices=prices)
    builders = [data_agent.build, team_agent.build, analytics_agent.build, presentation_agent.build,
                lambda c: research_agent.build(c, 1), lambda c: research_agent.build(c, 2),
                lambda c: pm_agent.build(c, 1), lambda c: pm_agent.build(c, 2)]
    for build in builders:
        agent = build(ctx)
        assert agent.model == "claude-opus-5-5" and agent.hooks is ctx.hooks


def test_views_row_is_display_rounded(offline_run):
    row = views.row(offline_run, "SPY")
    assert row["total_return"].endswith("%") and row["sharpe"].count(".") == 1
