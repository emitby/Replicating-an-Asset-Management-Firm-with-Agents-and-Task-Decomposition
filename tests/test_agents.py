"""Agent and harness tests with a scripted fake Claude client: no API calls."""

import json

import pytest

from conftest import FakeClaude, response, text, tool_use
from fixtures import VALID_TEAM
from strategy.agents import analytics_agent, backtest_agent, presentation_agent, team_agent
from strategy.agents.runtime import AgentError, BudgetExceeded, Trace
from strategy.config import PipelineConfig, WINDOWS
from strategy.context import RunContext
from strategy.harness import StageError, run_stage


def make_ctx(workdir, client, prices=None, **cfg):
    ctx = RunContext(run_dir=workdir, cfg=PipelineConfig(**cfg), trace=Trace(workdir / "trace.jsonl"), client=client)
    ctx.prices = prices
    return ctx


def tool_results(client, request_idx):
    return client.requests[request_idx]["messages"][-1]["content"]


def test_backtest_agent_must_run_every_candidate(workdir, prices):
    client = FakeClaude(
        response(tool_use("a", "run_ma_backtest", ma_days=50), tool_use("b", "run_walk_forward"), stop="tool_use"),
        response(tool_use("c", "compare_candidates"), stop="tool_use"),
        response(tool_use("d", "save_backtest", methodology_summary="Walk-forward."), stop="tool_use"),
        response(text("Saved.")),
    )
    ctx = make_ctx(workdir, client, prices)
    with pytest.raises(StageError):
        run_stage(ctx, "backtest")
    save_result = tool_results(client, 3)[0]
    assert save_result["is_error"] and "missing MA [5, 20, 200]" in save_result["content"]


def full_backtest_script():
    return [
        response(*[tool_use(f"m{n}", "run_ma_backtest", ma_days=n) for n in (5, 20, 50, 200)],
                 tool_use("wf", "run_walk_forward"), stop="tool_use"),
        response(tool_use("c", "compare_candidates"), stop="tool_use"),
        response(tool_use("s", "save_backtest", methodology_summary="Walk-forward selection."), stop="tool_use"),
        response(text("Backtest saved.")),
    ]


def test_backtest_then_analytics_findings_are_number_checked(workdir, prices):
    ctx = make_ctx(workdir, FakeClaude(*full_backtest_script()), prices)
    run_stage(ctx, "backtest")
    assert ctx.path("backtest.json").exists() and ctx.path("returns.csv").exists()

    sharpe = round(ctx.backtest["candidates_in_sample"]["MA200"]["sharpe"], 2)  # any real number
    good = ["Finding one is qualitative.", "Drawdowns were smaller in stress periods.",
            f"The 200-day rule had an in-sample Sharpe of {sharpe:.2f}.", "It lagged in strong rallies."]
    ctx.client = FakeClaude(
        response(*[tool_use(f"w{w}", "compute_metrics", window=w) for w in WINDOWS],
                 tool_use("r", "rolling_analysis"), stop="tool_use"),
        response(tool_use("bad", "save_analytics", findings=good[:3] + ["It beat SPY by 87.65% per year."]), stop="tool_use"),
        response(tool_use("ok", "save_analytics", findings=good), stop="tool_use"),
        response(text("Saved.")),
    )
    run_stage(ctx, "analytics")
    rejected = tool_results(ctx.client, 2)[0]
    assert rejected["is_error"] and "87.65%" in rejected["content"]
    assert ctx.analytics["findings"] == good


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
    assert "real firm" in tool_results(client, 1)[0]["content"]
    assert len(ctx.team["members"]) == 6 and ctx.path("team.json").exists()


@pytest.fixture
def ready_ctx(workdir, prices):
    """A context with backtest, analytics and team done, ready for the Presentation Agent."""
    ctx = make_ctx(workdir, FakeClaude(*full_backtest_script()), prices)
    run_stage(ctx, "backtest")
    ctx.client = FakeClaude(
        response(*[tool_use(f"w{w}", "compute_metrics", window=w) for w in WINDOWS],
                 tool_use("r", "rolling_analysis"), stop="tool_use"),
        response(tool_use("s", "save_analytics", findings=["A.", "B.", "C.", "D."]), stop="tool_use"),
        response(text("ok")),
    )
    run_stage(ctx, "analytics")
    from strategy.team import validate_team
    ctx.team, _ = validate_team(VALID_TEAM)
    return ctx


def test_presentation_agent_guardrails_and_pdf(ready_ctx):
    from strategy.agents.presentation_agent import METRIC_WORDS, WINDOW_WORDS
    from strategy.analytics import adverse_windows
    ctx = ready_ctx
    spy_mdd = ctx.analytics["windows"]["SI"]["series"]["SPY"]["max_drawdown"]
    adverse = adverse_windows(ctx.analytics)
    acknowledgements = [f"Over the {WINDOW_WORDS[a['window']][1]} window the strategy had a weaker "
                        f"{' and '.join(METRIC_WORDS[m][0] for m in a['worse_on'])} than SPY." for a in adverse][:6]
    slides = [tool_use(f"s{c}", "add_slide", title=f"Slide {c}", bullets=["Disciplined, rules-based allocation."])
              for c in "ABCD"]
    ctx.client = FakeClaude(
        response(tool_use("l", "list_metrics"), tool_use("c1", "render_chart", kind="equity_vs_spy"),
                 tool_use("c2", "render_chart", kind="drawdowns"), stop="tool_use"),
        # violation: invented number and promissory language
        response(tool_use("bad", "add_slide", title="Why invest", bullets=["Guaranteed 99.9% upside."]), stop="tool_use"),
        response(tool_use("p1", "add_slide", title="Performance vs SPY", bullets=["Growth of $10,000 shown."],
                          chart="equity_vs_spy"),
                 tool_use("p2", "add_slide", title="Drawdown protection",
                          bullets=[f"SPY's worst drawdown was {abs(spy_mdd) * 100:.1f}%."], chart="drawdowns"),
                 *slides, stop="tool_use"),
        response(tool_use("early", "build_pdf"), stop="tool_use"),
        response(tool_use("m", "add_standard_page", page="metrics_table"),
                 tool_use("i", "add_standard_page", page="in_sample_comparison"),
                 tool_use("t", "add_standard_page", page="team"), stop="tool_use"),
        response(tool_use("b", "build_pdf"), stop="tool_use"),
        *([] if not adverse else [
            response(tool_use("tradeoffs", "add_slide", title="Trade-offs", bullets=acknowledgements), stop="tool_use"),
            response(tool_use("b2", "build_pdf"), stop="tool_use")]),
        response(text("Deck built.")),
    )
    run_stage(ctx, "presentation")
    if adverse:   # first build_pdf was blocked by the balance check, then succeeded after acknowledging
        blocked = tool_results(ctx.client, 6)[0]
        assert blocked["is_error"] and "Balance check failed" in blocked["content"]

    bad = tool_results(ctx.client, 2)[0]
    assert bad["is_error"] and "99.9%" in bad["content"] and "guarantee" in bad["content"].lower()
    early = tool_results(ctx.client, 4)[0]
    assert early["is_error"] and "standard pages" in early["content"]
    assert ctx.path("presentation.pdf").exists()
    perf = {s["title"]: s["performance"] for s in ctx.slides if s["type"] == "slide"}
    # Disclosure is decided by code: charts or any digit -> performance footer.
    assert perf["Performance vs SPY"] and perf["Drawdown protection"] and not perf["Slide A"]


def test_every_citable_percentage_is_traceable_in_pdf(ready_ctx):
    """Traceability by construction: every percentage the Presentation Agent can see in list_metrics
    must appear in the code-generated pages, so any figure it cites can be found by a reader."""
    import re
    from pypdf import PdfReader
    from strategy.agents.presentation_agent import build as build_presentation, render_deck
    ctx = ready_ctx
    tools = build_presentation(ctx).tools
    shown = json.dumps(tools["list_metrics"].handler())
    citable = set(re.findall(r"-?\d+\.\d%", shown))
    ctx.slides = [{"type": "metrics_table"}, {"type": "in_sample_comparison"}, {"type": "team"}]
    pdf = render_deck(ctx)
    text = " ".join(p.extract_text() for p in PdfReader(str(pdf)).pages)
    missing = sorted(v for v in citable if v not in text)
    assert not missing, f"Citable but not shown in any table: {missing[:20]}"


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


def test_all_agents_use_the_configured_model(workdir):
    for module in (backtest_agent, analytics_agent, presentation_agent, team_agent):
        agent = module.build(make_ctx(workdir, None))
        assert agent.model == "claude-opus-5-5"
