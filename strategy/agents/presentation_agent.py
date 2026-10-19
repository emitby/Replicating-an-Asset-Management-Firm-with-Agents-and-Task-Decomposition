"""Presentation Agent: writes the investor pitch and builds the PDF."""

from strategy import charts
from strategy.agents.display import display
from strategy.analytics import adverse_windows
from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.guardrails import check_text, persona_mentions
from strategy.paths import write_json
from strategy.pdf import Deck

STANDARD_PAGES = ("metrics_table", "in_sample_comparison", "team")
REQUIRED_CHARTS = ("equity_vs_spy", "drawdowns")
MAX_SLIDES, MIN_SLIDES = 12, 6

PROMPT = """You are the Presentation Agent. You build an investor presentation that makes a clear, honest case for investing in a systematic strategy. The strategy holds SPY when SPY is above a moving average and IEF otherwise. The moving average (5, 20, 50 or 200 days) is re-selected each January using only prior data (walk-forward).

Audience: sophisticated investors and allocators. Tone: confident, specific and balanced. A persuasive deck that is trustworthy, not hype.

Build the deck:
1. Call list_metrics to see every result you may cite, and get_team for the team.
2. Render the charts you'll use. Always include equity_vs_spy and drawdowns. Also available: rolling_1y, allocation, window_returns, ma_selection, calendar_years.
3. Add {min_slides}-{max_slides} slides with add_slide, in presentation order. A good arc:
   - executive summary (the investment case in 3-4 bullets)
   - the problem the strategy addresses (equity drawdowns)
   - how the strategy works (rules, walk-forward discipline)
   - performance vs SPY (with chart)
   - risk and drawdown protection (with chart)
   - performance by period: 3M, 1Y, 3Y, 5Y
   - when it lags (honest trade-offs)
   - portfolio fit: who it suits and how it complements other holdings
   - next steps (generic, e.g. "request the full methodology"; no named contacts)
4. Insert the standard pages where they belong with add_standard_page:
   - metrics_table (risk and return by period)
   - in_sample_comparison (context on each MA)
   - team (the digital investment team bios)
5. Call build_pdf. Then reply with a 2-3 sentence summary of the deck.

Rules, enforced by code:
- Every number must come from list_metrics, quoted as displayed (percentages to 1 decimal, ratios to 2) or rounded further. Never compute differences or new figures. Write "lower drawdown than SPY (X% vs Y%)", not a computed gap.
- No promises or certainty about future results: no "guaranteed", "will outperform", "risk-free" and so on.
- In-sample comparisons must be described as hindsight context, never as the strategy's result.
- Pair the strategy's statistics with SPY's comparable figure, e.g. a best or worst rolling year for both.
- The team appears only on the code-rendered team pages. Never name team members on your slides, and never present them as contacts. They are fictional.
- No urgency or market-timing language ("act now", "why now").
- Label partial calendar years as year-to-date, as list_metrics does.
- Balance: list_metrics.MUST_ACKNOWLEDGE lists windows where the strategy did worse than SPY. Each one must appear on a slide, typically the trade-offs slide, naming the window and the metric. build_pdf enforces this. Don't lead with a benefit that only holds in some periods without saying so.
- Describe it accurately: a tactical SPY/Treasury allocation strategy, not an "equity strategy". It captures only part of SPY's upside, so don't claim it "stays invested in rising markets" without qualification.
- Every figure you cite also appears in the code-generated tables or the supporting-data appendix, so readers can trace it.
- Bullets: at most 6 per slide, each under 220 characters. Slide titles under 70 characters.
- Disclosures and footers are added automatically. Don't write them.
If add_slide reports a violation, rewrite that slide and add it again."""


def build(ctx):
    def list_metrics():
        if ctx.analytics is None or ctx.backtest is None:
            raise ToolError("Analytics and backtest must be saved first.")
        ctx.record("list_metrics")
        a, b = ctx.analytics, ctx.backtest
        counts = {}
        for h in b["selection_history"]:
            counts[f"{h['chosen_ma']}-day"] = counts.get(f"{h['chosen_ma']}-day", 0) + 1
        return {
            "period": {"out_of_sample_start": b["oos_start"], "end": b["end"],
                       "years_of_walk_forward_selection": b["years_selected"]},
            "windows": display(tabled_windows(a["windows"])),
            "rolling_1y": display(a["rolling_1y"]),
            "growth_of_10000": {k: f"${v:,.0f}" for k, v in a["growth_of_10000"].items()},
            "calendar_years": {_year_label(y, b["end"]): {k: f"{v * 100:.1f}%" for k, v in row.items()}
                               for y, row in a["calendar_years"].items()},
            "ma_selection_counts": counts,
            "current_allocation_spy": display(b["current_allocation_spy"], "current_allocation_spy"),
            "in_sample_candidates_HINDSIGHT_ONLY": display(
                {k: {f: v[f] for f in CANDIDATE_FIELDS} for k, v in b["candidates_in_sample"].items()}),
            "MUST_ACKNOWLEDGE": [
                f"{x['window']}: strategy was worse than SPY on {', '.join(x['worse_on'])}"
                for x in adverse_windows(a)],
        }

    def get_team():
        if ctx.team is None:
            raise ToolError("The team isn't ready yet.")
        return [{"name": m["name"], "title": m["title"], "focus": m["focus"]} for m in ctx.team["members"]]

    def render_chart(kind):
        if ctx.returns is None:
            raise ToolError("No returns loaded.")
        try:
            path = charts.render(kind, ctx.path("charts"), ctx.returns, analytics=ctx.analytics,
                                 history=(ctx.backtest or {}).get("selection_history"))
        except charts.ChartError as exc:
            raise ToolError(str(exc)) from None
        ctx.charts[kind] = path
        ctx.record("render_chart", kind=kind)
        return {"rendered": kind}

    def add_slide(title, bullets, chart=None):
        if len([s for s in ctx.slides if s["type"] == "slide"]) >= MAX_SLIDES:
            raise ToolError(f"Maximum {MAX_SLIDES} slides.")
        if not 1 <= len(bullets) <= 6:
            raise ToolError("Use 1-6 bullets.")
        if len(title) > 70 or any(len(b) > 220 for b in bullets):
            raise ToolError("Title must be under 70 characters, and each bullet under 220.")
        if chart and chart not in ctx.charts:
            raise ToolError(f"Render chart {chart!r} first.")
        problems = check_text(" \n".join([title, *bullets]), ctx.number_index())
        named = persona_mentions(" ".join([title, *bullets]), ctx.team)
        if named:
            problems.append(f"Names fictional personas {named}. Team members may appear only on the "
                            "labeled team pages (add_standard_page 'team'). Refer to 'the investment team' instead, "
                            "and never present a persona as a real contact.")
        if problems:
            raise ToolError("Slide rejected by guardrails:\n" + "\n".join(problems))
        # The builder, not the agent, decides when the performance disclosure applies.
        performance = bool(chart) or any(ch.isdigit() for ch in " ".join([title, *bullets]))
        ctx.slides.append({"type": "slide", "title": title, "bullets": bullets, "chart": chart,
                           "performance": performance})
        ctx.record("add_slide", title=title)
        return {"added": title, "slide_number": len(ctx.slides) + 1, "performance_disclosure": performance}

    def add_standard_page(page):
        if page not in STANDARD_PAGES:
            raise ToolError(f"Standard pages: {list(STANDARD_PAGES)}.")
        if any(s["type"] == page for s in ctx.slides):
            raise ToolError(f"{page} already added.")
        if page == "team" and ctx.team is None:
            raise ToolError("The team isn't ready yet.")
        ctx.slides.append({"type": page})
        ctx.record("add_standard_page", page=page)
        return {"added": page, "position": len(ctx.slides) + 1}

    def build_pdf():
        n_slides = len([s for s in ctx.slides if s["type"] == "slide"])
        if n_slides < MIN_SLIDES:
            raise ToolError(f"Add at least {MIN_SLIDES} slides (have {n_slides}).")
        used_charts = {s.get("chart") for s in ctx.slides}
        missing = [c for c in REQUIRED_CHARTS if c not in used_charts]
        if missing:
            raise ToolError(f"Slides must use charts {missing}.")
        missing_pages = [p for p in STANDARD_PAGES if not any(s["type"] == p for s in ctx.slides)]
        if missing_pages:
            raise ToolError(f"Add standard pages {missing_pages}.")
        unacknowledged = unacknowledged_adverse(ctx.analytics, ctx.slides)
        if unacknowledged:
            raise ToolError("Balance check failed: the deck must acknowledge where the strategy was worse than SPY. "
                            f"Not yet mentioned: {unacknowledged}. Add or revise a slide that names the window "
                            "(e.g. '5-year') and the metric (drawdown and/or Sharpe).")
        path = render_deck(ctx)
        ctx.record("build_pdf")
        return {"built": path.name, "pages": len(ctx.slides) + 2}

    tools = [
        Tool("list_metrics", "All results you may cite, display-rounded.", schema(), list_metrics),
        Tool("get_team", "Names, titles and focus areas of the digital investment team.", schema(), get_team),
        Tool("render_chart", "Render a chart for use on a slide.",
             schema({"kind": {"type": "string", "enum": list(charts.CHART_KINDS)}}, ["kind"]), render_chart),
        Tool("add_slide", "Append a slide. Text is checked by guardrails.",
             schema({"title": {"type": "string"}, "bullets": {"type": "array", "items": {"type": "string"}},
                     "chart": {"type": "string", "enum": list(charts.CHART_KINDS)}}, ["title", "bullets"]),
             add_slide),
        Tool("add_standard_page", "Insert a code-generated page at the current position.",
             schema({"page": {"type": "string", "enum": list(STANDARD_PAGES)}}, ["page"]), add_standard_page),
        Tool("build_pdf", "Build presentation.pdf. Checks required content first.", schema(), build_pdf),
    ]
    prompt = PROMPT.format(min_slides=MIN_SLIDES, max_slides=MAX_SLIDES)
    return Agent(ctx.client, "Presentation Agent", prompt, tools, ctx.trace, effort="medium",
                 max_turns=40, token_budget=ctx.cfg.token_budget, model=ctx.cfg.model)


# Traceability contract: the agent sees exactly the fields the code-generated tables print,
# so every figure it cites can be found by a reader (tested in test_every_citable_percentage_is_traceable_in_pdf).
MAIN_FIELDS = ("total_return", "cagr", "volatility", "sharpe", "sortino", "max_drawdown", "calmar", "beta",
               "correlation", "up_capture", "down_capture", "hit_rate", "best_day", "worst_day")
MIX_FIELDS = ("total_return", "cagr", "volatility", "sharpe", "max_drawdown", "calmar")
CANDIDATE_FIELDS = ("cagr", "volatility", "sharpe", "max_drawdown", "switches", "pct_time_in_spy")


def tabled_windows(windows):
    out = {}
    for w, data in windows.items():
        fields = {"Strategy": MAIN_FIELDS, "SPY": MAIN_FIELDS, "60/40": MIX_FIELDS}
        out[w] = {"window": w, "start": data["start"], "end": data["end"], "annualized": data["annualized"],
                  "series": {s: {k: v for k, v in data["series"][s].items() if k in fields[s]}
                             for s in data["series"]},
                  "strategy_activity": data["strategy_activity"]}
    return out


WINDOW_WORDS = {
    "3M": ("3m", "3-month", "three-month", "3 month", "past quarter", "last quarter"),
    "1Y": ("1y", "1-year", "one-year", "1 year", "past year", "last year", "trailing year", "12-month", "12 month"),
    "3Y": ("3y", "3-year", "three-year", "3 year"),
    "5Y": ("5y", "5-year", "five-year", "5 year"),
    "SI": ("since inception", "since 2007", "full period", "since the walk-forward"),
}
METRIC_WORDS = {"max_drawdown": ("drawdown",), "sharpe": ("sharpe", "risk-adjusted")}


def unacknowledged_adverse(analytics, slides):
    """Adverse (window, metric) pairs that no agent slide mentions together."""
    texts = [" ".join([s["title"], *s["bullets"]]).lower() for s in slides if s["type"] == "slide"]
    missing = []
    for item in adverse_windows(analytics):
        for metric in item["worse_on"]:
            if not any(any(w in t for w in WINDOW_WORDS[item["window"]]) and
                       any(m in t for m in METRIC_WORDS[metric]) for t in texts):
                missing.append(f"{item['window']} {metric}")
    return missing


def _year_label(year, end):
    """'2026 YTD (through 2026-10-16)' for an incomplete final year, else '2025'."""
    year = int(year)
    if str(year) == end[:4] and end[5:] < "12-24":
        return f"{year} YTD (through {end})"
    return str(year)


def render_deck(ctx):
    """Assemble the PDF from ctx.slides. Deterministic: also used by tests and re-renders."""
    deck = Deck("SPY / IEF Trend Rotation", "A rules-based approach to managing equity drawdowns",
                cost_bps=ctx.cfg.strategy.cost_bps)
    for s in ctx.slides:
        if s["type"] == "slide":
            chart = ctx.charts.get(s["chart"]) if s.get("chart") else None
            deck.add_slide(s["title"], s["bullets"], chart, s["performance"])
        elif s["type"] == "metrics_table":
            deck.add_metrics_table(ctx.analytics)
        elif s["type"] == "in_sample_comparison":
            deck.add_candidates_table(ctx.backtest["candidates_in_sample"], ctx.backtest["selection_history"],
                                      period=f"{ctx.backtest['oos_start']} to {ctx.backtest['end']}")
        elif s["type"] == "team":
            deck.add_team(ctx.team)
    deck.add_supporting_data(ctx.analytics)      # always last before disclosures: makes cited figures traceable
    write_json(ctx.path("slides.json"), ctx.slides)
    return deck.build(ctx.path("presentation.pdf"))


def task(ctx):
    return "Build the investor presentation and the PDF."
