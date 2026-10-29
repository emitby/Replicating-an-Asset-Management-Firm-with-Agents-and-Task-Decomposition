"""Presentation Agent: writes the slides of the "Agentic Capital Management Strategy Presentation".

The agent writes slides into fixed sections (executive summary, strategy, round
1, PM selection, round 2, risk, diversification). Every slide is guardrail-
checked when added. `build_deck` enforces the deck's required content, saves
the slides to deck.json and calls `pdf.build_from_run`, which renders the whole
PDF (code pages, tables, decision log, meeting, team, disclosures) from saved
artifacts. Because the PDF is built from deck.json, it can be edited and rebuilt
later with ``build-pdf`` without this agent.
"""

from strategy.agents import views
from strategy.agents.display import display
from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.charts import CHART_KINDS, REQUIRED_CHARTS, ChartData, render
from strategy.guardrails import check_text, persona_mentions
from strategy.paths import write_json
from strategy.pdf import SECTION_LIMITS, SECTIONS, SUBTITLE, TITLE, build_from_run
from strategy.ranking import rule_text

MAX_BULLETS, MAX_TITLE, MAX_BULLET = 6, 80, 240
# What each section must say, checked on the section's combined text (lower case). Each entry is
# (requirement shown to the agent, alternatives: any one word must appear).
SECTION_RULES = {
    # User requirement: correlation with SPY is highlighted wherever the strategy's benefits are explained.
    "executive_summary": [("compare with SPY", ("spy",)), ("correlation with SPY", ("correlat",))],
    "round1": [("at least one 'Pro:' bullet", ("pro:",)), ("at least one 'Con:' bullet", ("con:",))],
    "pm_selection": [("explain the selection rule (total return)", ("total return",))],
    "round2": [("say what the proposals changed (lookback or moving average)", ("lookback", "moving average", "sma"))],
    "risk": [("drawdowns", ("drawdown",)), ("no trading costs", ("cost",)),
             ("selection with hindsight across many tested strategies", ("hindsight", "in-sample", "selection bias")),
             ("the long/short result", ("short",))],
    "diversification": [("diversification", ("diversif",)), ("correlation with SPY", ("correlat",)),
                        # Balance on the page itself, not only in the footer (visual review: the section was one-sided).
                        ("a caveat on the same slides: hindsight selection or the years it lagged SPY",
                         ("hindsight", "lagged", "lag ", "underperform"))],
}

PROMPT = """You are the Presentation Agent at Agentic Capital Management. You write the slides of the "{title}" for an investment committee. Code renders the PDF and owns these pages, so do NOT write slides for them: page 1 (how the agents produced the deck), the workflow flowchart, the harness/hooks and guardrails/evals pages, the simulated strategy meeting, the decision log of the Research <-> Portfolio Manager exchange, the two analysis-table pages, the team pages and the disclosures.

The strategy: {rule}
The process: the Research Agent backtested every combination, the Portfolio Manager Agent picked the top 5 by total return vs SPY, proposed 5 new parameter sets, the Research Agent ran them, and any that beat the weakest of the top 5 replaced it.

Steps:
1. Call list_metrics and get_dialogue. Read them fully.
2. Render charts with render_chart and use them on slides. Required: {charts}.
3. Add slides with add_slide, in these sections (min-max slides each):
{sections}
4. Call build_deck. If it reports problems, fix them with revise_slide or add_slide, and call build_deck again until it succeeds.

Section content:
- executive_summary: what was tested, the final line-up and how it compares with SPY and QQQ, its correlation with SPY (the corr_spy figures), and the main trade-off.
- strategy: how the ranking works, the signals, the lookbacks and the three portfolio rules.
- round1: what the {n} strategies showed, with 'Pro:' and 'Con:' bullets (start the bullet with them).
- pm_selection: how the PM chose the top 5 (highest total return) and why it proposed each new parameter set.
- round2: what the proposals changed and whether they replaced anything.
- risk: drawdowns and volatility vs SPY, no trading costs, the strategies were selected with hindsight from many tested on one period, and how the long/short variant did.
- diversification: a positive, persuasive marketing section on how this strategy can fit in a diversified portfolio, for example as a satellite next to a core equity holding: its rotation across stocks, bonds, gold, oil and credit, its correlations, and the SPY blend. Lead with the correlation with SPY (corr_spy): it is the core of the diversification case; contrast it with QQQ's correlation with SPY. Be enthusiastic but factual, and keep one balancing bullet on these slides (the results were selected with hindsight, and the years it lagged SPY). Describe; don't instruct the reader ("investors could", not "diversify").

Rules:
- Quote only numbers from list_metrics or get_dialogue, exactly as displayed (percentages to 1 decimal, ratios to 2), or rounded further. Never compute new numbers (no differences, sums or averages of your own).
- Pair a strategy statistic with SPY's where it helps. Label year-to-date periods as YTD.
- Whenever a slide explains a benefit of the strategy, cite its correlation with SPY, written as "correlation with SPY of 0.16" (code highlights these phrases in the PDF).
- Name the strategy every figure belongs to, and never attach one strategy's figure to another. A range ("X to Y") must be the true minimum and maximum of exactly the strategies you name.
- No promises about future returns, no "guaranteed", "will outperform", "can't lose", no urgency. Never name team members.
- At most {mb} bullets per slide, each under {ml} characters; titles under {mt} characters.
- Don't write disclosures or footers; code adds them."""


def build(ctx):
    """Build the Presentation Agent.

    Args:
        ctx: the run context (needs research, PM, analytics and team results).

    Returns:
        A configured `Agent`.
    """
    cfg = ctx.cfg.ranking

    def need():
        missing = [n for n, v in (("analytics", ctx.analytics), ("final decision", ctx.pm.get("final")),
                                  ("team", ctx.team)) if not v]
        if missing:
            raise ToolError(f"Missing inputs: {missing}.")

    def list_metrics():
        need()
        ctx.record("list_metrics")
        final = ctx.pm["final"]["final"]
        r1 = ctx.research[1]["ids"]
        an = ctx.analytics
        keep = ("total_return", "cagr", "volatility", "max_drawdown", "sharpe", "correlation", "beta",
                "up_capture", "down_capture")
        windows = {w: {"start": an["windows"][w]["start"], "end": an["windows"][w]["end"],
                       "series": {s: display({k: v for k, v in m.items() if k in keep})
                                  for s, m in an["windows"][w]["series"].items()}} for w in an["windows"]}
        fit = an["portfolio_fit"]
        last_year = max(an["calendar_years"], key=int)
        return {
            "window": views.window(ctx), "strategies_tested": len(ctx.specs),
            "benchmarks": views.benchmarks(ctx),
            "final_lineup": views.ranked(ctx, final),
            "round1_top5": views.ranked(ctx, [p["id"] for p in ctx.pm["top5"]]),
            "round1_top10": views.ranked(ctx, r1)[:10],
            "round1_bottom5": views.ranked(ctx, r1)[-5:],
            "round1_beating_spy": int((ctx.scores.loc[r1, "excess_vs_spy"] > 0).sum()),
            "round1_families": display(ctx.facts.get("round1_family", {})),
            "proposals": views.ranked(ctx, [p["id"] for p in ctx.pm["proposals"]]),
            "replacements": [{"added": views.row(ctx, r["added"]), "removed": views.row(ctx, r["removed"])}
                             for r in ctx.pm["final"]["replacements"]],
            "by_period": windows,
            "calendar_years": {(f"{y} YTD" if y == last_year else y): {k: f"{v * 100:.1f}%" for k, v in row.items()}
                               for y, row in an["calendar_years"].items()},
            "growth_of_10000": {k: f"${v:,.0f}" for k, v in an["growth_of_10000"].items()},
            "portfolio_fit": {
                "blend": f"{100 - round(fit['blend_weight'] * 100)}% SPY + {round(fit['blend_weight'] * 100)}% strategy",
                "correlation": {s: {a: f"{v:.2f}" for a, v in row.items()} for s, row in fit["correlation"].items()},
                "blends": {s: display({k: v for k, v in m.items() if k in keep}) for s, m in fit["blends"].items()},
                "spy_alone": display({k: v for k, v in fit["spy"].items() if k in keep})},
            "analytics_findings": an["findings"],
            "costs_modeled": "none (no trading costs, fees or taxes)",
        }

    def get_dialogue():
        need()
        ctx.record("get_dialogue")
        return {"dialogue": ctx.dialogue, "meeting": ctx.pm.get("meeting", [])}

    def get_team():
        need()
        ctx.record("get_team")
        return {"note": "Personas appear only on the code-rendered team pages. Never name them on slides.",
                "members": [{"name": m["name"], "title": m["title"], "focus": m["focus"]} for m in ctx.team["members"]]}

    def chart_data():
        returns = ctx.returns
        return ChartData(returns, ctx.scores, {sid: s.to_dict() for sid, s in ctx.specs.items()}, ctx.pm,
                         ctx.analytics, ctx.research[1]["ids"])

    def render_chart(kind):
        need()
        if kind not in CHART_KINDS:
            raise ToolError(f"Charts are {list(CHART_KINDS)}.")
        ctx.record("render_chart", kind=kind)
        ctx.charts[kind] = render(kind, ctx.path("charts"), chart_data())
        return {"rendered": kind, "use_on_slide": f"chart='{kind}'"}

    def validated(section, title, bullets, chart):
        if section not in SECTIONS:
            raise ToolError(f"Sections are {list(SECTIONS)}.")
        if not 1 <= len(bullets) <= MAX_BULLETS:
            raise ToolError(f"Use 1-{MAX_BULLETS} bullets.")
        if len(title) > MAX_TITLE or any(len(b) > MAX_BULLET for b in bullets):
            raise ToolError(f"Titles under {MAX_TITLE} characters, bullets under {MAX_BULLET}.")
        if chart and chart not in ctx.charts:
            raise ToolError(f"Render chart {chart!r} first.")
        problems = check_text(" \n".join([title, *bullets]), ctx.number_index())
        names = persona_mentions(" ".join([title, *bullets]), ctx.team)
        if names:
            problems.append(f"Don't name team members on slides: {names}.")
        if problems:
            raise ToolError("Slide rejected:\n" + "\n".join(problems))
        return {"section": section, "title": title, "bullets": bullets, "chart": chart,
                "performance": bool(chart) or any(ch.isdigit() for ch in " ".join(bullets))}

    def add_slide(section, title, bullets, chart=None):
        need()
        if sum(s["section"] == section for s in ctx.slides) >= SECTION_LIMITS.get(section, (0, 0))[1]:
            raise ToolError(f"Section {section!r} already has its maximum of {SECTION_LIMITS[section][1]} slides; "
                            "use revise_slide.")
        slide = validated(section, title, bullets, chart)
        ctx.record("add_slide", title=title)
        ctx.slides.append(slide)
        return {"added": title, "slides": len(ctx.slides)}

    def revise_slide(existing_title, section, title, bullets, chart=None):
        idx = next((i for i, s in enumerate(ctx.slides) if s["title"] == existing_title), None)
        if idx is None:
            raise ToolError(f"No slide titled {existing_title!r}. Titles: {[s['title'] for s in ctx.slides]}.")
        ctx.slides[idx] = validated(section, title, bullets, chart)
        ctx.record("revise_slide", title=title)
        return {"revised": title}

    def deck_problems():
        """Everything that must be true of the slides before the PDF is built."""
        problems = []
        for sec in SECTIONS:
            lo, hi = SECTION_LIMITS[sec]
            slides = [s for s in ctx.slides if s["section"] == sec]
            if not lo <= len(slides) <= hi:
                problems.append(f"Section {sec!r} needs {lo}-{hi} slides (has {len(slides)}).")
            text = " ".join(" ".join([s["title"], *s["bullets"]]) for s in slides).lower()
            for need_text, words in SECTION_RULES.get(sec, []):
                if slides and not any(w in text for w in words):
                    problems.append(f"Section {sec!r} must cover: {need_text}.")
        used = {s["chart"] for s in ctx.slides if s["chart"]}
        missing = [k for k in REQUIRED_CHARTS if k not in used]
        if missing:
            problems.append(f"Use these charts on slides: {missing}.")
        return problems

    def build_deck():
        need()
        problems = deck_problems()
        if problems:
            raise ToolError("Not ready:\n" + "\n".join(problems))
        ctx.record("build_deck")
        write_json(ctx.path("deck.json"), {"title": TITLE, "subtitle": SUBTITLE, "slides": ctx.slides,
                                           "charts": sorted({s["chart"] for s in ctx.slides if s["chart"]})})
        path = build_from_run(ctx.run_dir)
        return {"built": path.name, "slides": len(ctx.slides)}

    bullets = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": MAX_BULLETS}
    section = {"type": "string", "enum": list(SECTIONS)}
    chart = {"type": "string", "enum": list(CHART_KINDS)}
    tools = [
        Tool("list_metrics", "Every verified figure for the slides: final line-up, rounds, by-period metrics, calendar "
             "years, portfolio fit, analytics findings.", schema(), list_metrics),
        Tool("get_dialogue", "The Research <-> Portfolio Manager messages and decisions, and the meeting script.",
             schema(), get_dialogue),
        Tool("get_team", "The fictional team (for context only; never name them on slides).", schema(), get_team),
        Tool("render_chart", "Render a chart for use on a slide.", schema({"kind": chart}, ["kind"]), render_chart),
        Tool("add_slide", "Add a slide to a section (guardrail-checked).",
             schema({"section": section, "title": {"type": "string"}, "bullets": bullets, "chart": chart},
                    ["section", "title", "bullets"]), add_slide),
        Tool("revise_slide", "Replace an existing slide (same checks as add_slide).",
             schema({"existing_title": {"type": "string"}, "section": section, "title": {"type": "string"},
                     "bullets": bullets, "chart": chart}, ["existing_title", "section", "title", "bullets"]), revise_slide),
        Tool("build_deck", "Check the slides, save deck.json and render the PDF.", schema(), build_deck),
    ]
    sections = "\n".join(f"   - {s}: {lo}-{hi}" for s, (lo, hi) in SECTION_LIMITS.items())
    prompt = PROMPT.format(title=TITLE, rule=rule_text(cfg), charts=", ".join(REQUIRED_CHARTS), sections=sections,
                           n=cfg.grid_size, mb=MAX_BULLETS, ml=MAX_BULLET, mt=MAX_TITLE)
    return Agent(ctx.client, "Presentation Agent", prompt, tools, ctx.trace, effort="medium", max_turns=40,
                 token_budget=ctx.cfg.token_budget, model=ctx.cfg.model, hooks=ctx.hooks)


def task(ctx):
    """The Presentation Agent's task message."""
    return f"Write the slides for the {TITLE} and build the deck."
