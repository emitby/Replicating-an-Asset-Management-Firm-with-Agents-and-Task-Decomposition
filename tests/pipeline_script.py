"""A complete offline pipeline run: every agent driven by a scripted client, on synthetic prices.

`run_offline_pipeline` runs the real harness (stages, validators, hooks, cost
tracking, manifest, PDF) with `ScriptedClaude` in place of the API. Responses
that depend on earlier results (the PM's top 5, the final line-up) are
callables evaluated when the agent asks, reading the live run context.
"""

from conftest import ScriptedClaude, response, text, tool_use
from fixtures import VALID_TEAM
from strategy.agents import data_agent
from strategy.agents.runtime import Trace
from strategy.config import PipelineConfig
from strategy.context import RunContext
from strategy.harness import run_pipeline
from strategy.hooks import default_hooks
from strategy.ranking import apply_replacement, top_n

PROPOSALS = [("Top 1", 20, 10), ("Top 1", 10, 15), ("Top 3 mix", 30, 20), ("Top 3 mix", 20, 45), ("Top 1", 100, 120)]
MEETING = [
    ("Portfolio Manager Agent", "Our objective is the highest total return against SPY buy and hold."),
    ("Research Agent", "We compared every combination of signal, lookback and portfolio on the same dates."),
    ("Analytics Agent", "Drawdown and volatility matter as much as the return."),
    ("Portfolio Manager Agent", "So we keep the top five by total return and watch the risk."),
    ("Research Agent", "Short lookbacks led the ranking."),
    ("Analytics Agent", "The SPY blend shows how a sleeve fits next to a core holding."),
    ("Portfolio Manager Agent", "Agreed. We pick these five and disclose the hindsight."),
    ("Research Agent", "Round two tested five nearby parameter sets."),
    ("Analytics Agent", "Correlations with bonds and gold were low."),
]
CONSTRUCTIVE = [
    ("Portfolio Manager Agent", "Strong work. The correlation profiles are what make this line-up useful."),
    ("Research Agent", "Thank you. The low correlation with SPY comes from rotating across the macro basket."),
    ("Portfolio Manager Agent", "And the returns came from that basket, not from one lucky asset."),
    ("Analytics Agent", "The blend analysis shows how that helps a core holding."),
    ("Portfolio Manager Agent", "Keep that rigor in the next round."),
    ("Research Agent", "We will."),
]
HARSH = [
    ("Portfolio Manager Agent", "This process is sloppy. You picked winners with hindsight and called it research."),
    ("Research Agent", "We disclosed that."),
    ("Portfolio Manager Agent", "Disclosure is not rigor. No trading costs, and drawdowns deeper than SPY."),
    ("Analytics Agent", "The volatility is in the tables."),
    ("Portfolio Manager Agent", "Another review like this and I will be looking for new analysts."),
    ("Research Agent", "Understood."),
]
SLIDES = [
    ("executive_summary", "Executive Summary", ["The final line-up is compared with SPY and QQQ.",
                                                "Its correlation with SPY is low."], "growth_final"),
    ("strategy", "How the Ranking Works", ["Each month end the seven ETFs are ranked."], None),
    ("round1", "Round 1 Findings", ["Pro: short lookbacks led.", "Con: deep drawdowns."], "round1_heatmap"),
    ("pm_selection", "How the PM Chose", ["The top 5 by total return were kept."], "rounds_bars"),
    ("round2", "Round 2", ["The proposals changed the lookback and moving average."], None),
    ("risk", "Risks", ["Deeper drawdown than SPY.", "No trading costs.", "Selected with hindsight.",
                       "The long/short variant lagged."], "drawdowns_final"),
    ("diversification", "A Diversifier for a Core Equity Holding",
     ["It rotates across asset classes for diversification.", "Low correlation; see the SPY blend.",
      "Selected with hindsight, and it lagged SPY in some years."], "correlation"),
]


def _tool_turn(*calls):
    return response(*calls, stop="tool_use")


def scripts(ctx):
    """Per-agent scripted responses for one full run (callables read `ctx` when they run)."""
    picks = lambda: [{"id": i, "rationale": "High total return.", "pro": "Beat SPY.", "con": "Deep drawdown."}
                     for i in top_n(ctx.scores, 5, ctx.research[1]["ids"])]

    def decisions():
        out = apply_replacement(ctx.scores, [p["id"] for p in ctx.pm["top5"]], [p["id"] for p in ctx.pm["proposals"]])
        ids = set(out["final"]) | {r["removed"] for r in out["replacements"]}
        return [{"id": i, "rationale": "Ranked by total return.", "pro": "Strong return.", "con": "Volatile."}
                for i in sorted(ids)]

    return {
        "Data Agent": [
            _tool_turn(tool_use("d1", "fetch_prices", tickers=list(ctx.cfg.ranking.universe) + ["^IRX"], start="2014-01-01")),
            _tool_turn(tool_use("d2", "check_data_quality")),
            _tool_turn(tool_use("d3", "save_dataset")),
            response(text("Dataset saved.")),
        ],
        "Research Agent": [
            _tool_turn(tool_use("r1", "run_grid")),
            _tool_turn(tool_use("r2", "save_research", round=1, message_to_pm="Short lookbacks led round 1.",
                                findings=["Pro: short lookbacks led.", "Pro: the Top 1 rule had the highest returns.",
                                          "Con: drawdowns were deep.", "Con: many combinations were tested."])),
            response(text("Round 1 saved.")),
            _tool_turn(tool_use("r3", "get_proposals")),
            _tool_turn(*[tool_use(f"r4{i}", "run_strategy", portfolio=p, sma=s, lookback_days=d)
                         for i, (p, s, d) in enumerate(PROPOSALS)]),
            _tool_turn(tool_use("r5", "save_research", round=2, message_to_pm="All five proposals ran.",
                                findings=["Pro: one proposal ranked high.", "Pro: faster signals helped.",
                                          "Con: more trading.", "Con: no trading costs are modeled."])),
            response(text("Round 2 saved.")),
        ],
        "Portfolio Manager Agent": [
            _tool_turn(tool_use("p1", "get_results", round=1)),
            lambda: _tool_turn(tool_use("p2", "select_top5", picks=picks())),
            _tool_turn(tool_use("p3", "propose_strategies", message_to_research="Please run these five.", proposals=[
                {"portfolio": p, "sma": s, "lookback_days": d, "hypothesis": f"Try a {s}-day SMA over {d} days.",
                 "pro": "Faster signal.", "con": "More trading."} for p, s, d in PROPOSALS])),
            response(text("Round 1 decisions made.")),
            _tool_turn(tool_use("p4", "get_results", round=2)),
            lambda: _tool_turn(tool_use("p5", "finalize", decisions=decisions(), message="Final line-up set.")),
            _tool_turn(tool_use("p6", "write_meeting", lines=[{"speaker": s, "text": t} for s, t in MEETING])),
            _tool_turn(tool_use("p7", "write_feedback", constructive=[{"speaker": s, "text": t} for s, t in CONSTRUCTIVE],
                                harsh=[{"speaker": s, "text": t} for s, t in HARSH])),
            response(text("Final decisions made.")),
        ],
        "Analytics Agent": [
            _tool_turn(*[tool_use(f"a{w}", "compute_metrics", window=w) for w in ("1Y", "3Y", "5Y", "SI")],
                       tool_use("ac", "calendar_and_growth"), tool_use("af", "portfolio_fit")),
            _tool_turn(tool_use("as", "save_analytics", findings=[
                "The final strategies are compared with SPY and QQQ.", "Their drawdowns were deeper than SPY's.",
                "Correlation with bonds was low.", "Volatility was higher than SPY's.", "Results varied by period."])),
            response(text("Analytics saved.")),
        ],
        "Team Agent": [_tool_turn(tool_use("t1", "submit_team", members=VALID_TEAM)), response(text("Team saved."))],
        "Presentation Agent": [
            _tool_turn(tool_use("l1", "list_metrics"), tool_use("l2", "get_dialogue")),
            _tool_turn(*[tool_use(f"c{k}", "render_chart", kind=k) for k in
                         ("growth_final", "drawdowns_final", "round1_heatmap", "rounds_bars", "correlation")]),
            _tool_turn(*[tool_use(f"s{i}", "add_slide", section=sec, title=t, bullets=b, **({"chart": ch} if ch else {}))
                         for i, (sec, t, b, ch) in enumerate(SLIDES)]),
            _tool_turn(tool_use("b1", "build_deck")),
            response(text("Deck built.")),
        ],
    }


def run_offline_pipeline(run_dir, prices):
    """Run the whole pipeline offline in `run_dir`. Returns the finished `RunContext`.

    Side effects:
        Temporarily replaces the Data Agent's price fetch with the synthetic `prices`.
    """
    ctx = RunContext(run_dir=run_dir, cfg=PipelineConfig(), trace=Trace(run_dir / "trace.jsonl"), client=None,
                     hooks=default_hooks())
    ctx.client = ScriptedClaude(scripts(ctx))
    original = data_agent.fetch_prices
    data_agent.fetch_prices = lambda tickers, start, offline=False: prices[list(tickers)]
    try:
        run_pipeline(ctx)
    finally:
        data_agent.fetch_prices = original
    return ctx
