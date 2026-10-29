"""The "Agentic Capital Management Strategy Presentation" PDF (ReportLab, landscape).

The PDF is rendered **only from saved run artifacts** (`build_from_run`):
deck.json (the Presentation Agent's slides), research.json, pm.json,
dialogue.json, analytics.json, team.json, strategy_returns.csv and, when
present, manifest.json (for the run's cost). Nothing is read from live agent
state, so after a run the deck can be edited (deck.json or this file) and
rebuilt with ``build-pdf`` without re-running any agent or calling the API.

The builder, not any agent, owns:
- page 1 (how the agents produced the deck), the workflow flowchart and the
  harness/hooks/guardrails/evals pages, from `strategy.governance`;
- the two analysis-table pages (the only table pages, by construction);
- the decision log and the simulated meeting layout, with the "simulated" label;
- the performance footer on every performance page and the disclosures page;
- the fictional-persona stamp on every team card.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, KeepInFrame, Paragraph, Table, TableStyle

from strategy import governance
from strategy.charts import ChartData, render
from strategy.config import RankingConfig
from strategy.paths import confine, read_json
from strategy.ranking import rule_text
from strategy.team import FICTIONAL_LABEL

TITLE = "Agentic Capital Management Strategy Presentation"
SUBTITLE = ("Month-end ETF ranking on price and moving-average trends: AI research, portfolio manager review "
            "and results")
AUTHOR = "Agentic Capital Management (AI multi-agent research pipeline)"

PAGE_W, PAGE_H = landscape(letter)
NAVY = colors.HexColor("#1f4e79")
ORANGE = colors.HexColor("#c55a11")
GREY = colors.HexColor("#595959")
LIGHT = colors.HexColor("#eef3f8")
GREEN = colors.HexColor("#2e7d4f")

# Agent-written slide sections, in deck order. The code pages are placed between them (see `Deck.pages`).
SECTIONS = ("executive_summary", "strategy", "round1", "pm_selection", "round2", "risk", "diversification")
SECTION_LIMITS = {"executive_summary": (1, 2), "strategy": (1, 2), "round1": (1, 3), "pm_selection": (1, 2),
                  "round2": (1, 2), "risk": (1, 2), "diversification": (1, 2)}
TABLE_PAGE_PREFIX = "Analysis Table"
# The PM's two feedback pages (user request): kind -> (page title, simulated-content stamp).
FEEDBACK_PAGES = {
    "constructive": ("Constructive Feedback",
                     "Simulated conversation: the Portfolio Manager Agent's positive review of the analyst agents' work "
                     "(Research and Analytics Agents). AI agents, not people; every number was checked against the "
                     "backtest."),
    "harsh": ("Harsh Feedback",
              "Simulated conversation, deliberately harsh: the Portfolio Manager Agent attacks the analyst agents' "
              "process using the strategies' real weaknesses. The targets are AI agents, not people; every number was "
              "checked against the backtest."),
}
MAX_TABLE_PAGES = 2               # user requirement: the analysis tables fit on two pages

PERF_FOOTER = ("Hypothetical backtested performance, selected with hindsight from many tested combinations. Not actual "
               "trading. No trading costs, fees or taxes are included. Past performance does not guarantee future "
               "results. See Important Disclosures.")
GEN_FOOTER = "For discussion purposes only. Not an offer or solicitation. Produced by AI agents; see page 1."

DISCLOSURES = [
    "<b>Hypothetical, in-sample performance.</b> All performance shown is hypothetical and backtested. It does not "
    "represent actual trading or client accounts. The final strategies were selected because they had the highest "
    "total returns among {tested} combinations tested on the same historical period, so their results benefit from "
    "hindsight (selection bias) and overstate what an investor could have expected in advance. No representation is "
    "made that any account will or is likely to achieve similar results.",
    "<b>Methodology.</b> {rule} Returns use adjusted closing prices, which include dividends. Strategies are scored "
    "over a common window ({window}); the final year is year-to-date.",
    "<b>Costs and shorting.</b> Results <b>exclude trading costs</b>, management fees and taxes; strategies that "
    "change holdings often would be affected most. The long/short variant ignores borrow costs and interest on "
    "short proceeds; short positions can lose more than their initial value.",
    "<b>Portfolio blends.</b> SPY + strategy blends are rebalanced daily to fixed weights, without costs; this is a "
    "simplification of how a real portfolio would be managed.",
    "<b>Risk.</b> Investing involves risk, including loss of principal. Ranking strategies can concentrate in one "
    "ETF, switch holdings frequently, lag trend reversals and underperform buy-and-hold for long periods. Oil (USO), "
    "high-yield credit (JNK), gold (GLD) and Treasury (TLT, IEF) ETFs carry their own risks, including sharp losses.",
    "<b>Data.</b> Prices from Yahoo Finance via the yfinance library; not independently verified. The risk-free rate "
    "is the 13-week Treasury bill yield (^IRX).",
    f"<b>AI-generated content and personas.</b> The research, decisions, meeting script and slides were produced by "
    f"AI agents and checked by code. The meeting is simulated. The investment team members are {FICTIONAL_LABEL}s "
    "created by an AI system for illustration; they are not real people and their stated employers are fictional.",
    "<b>Not advice.</b> This presentation is for informational purposes only, and is not investment advice, an offer, "
    "or a solicitation to buy or sell any security.",
]

STYLES = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=NAVY),
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=12.5, leading=17, leftIndent=14,
                             bulletIndent=0, spaceAfter=7, textColor=colors.HexColor("#222222")),
    "bullet_wide": ParagraphStyle("bullet_wide", fontName="Helvetica", fontSize=15, leading=21, leftIndent=18,
                                  bulletIndent=0, spaceAfter=12, textColor=colors.HexColor("#222222")),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10.5, leading=14, spaceAfter=7),
    "body_big": ParagraphStyle("body_big", fontName="Helvetica", fontSize=12, leading=16.5, spaceAfter=9),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=NAVY, spaceAfter=5,
                         spaceBefore=4),
    "log": ParagraphStyle("log", fontName="Helvetica", fontSize=9.5, leading=12.3, spaceAfter=4, leftIndent=10,
                          bulletIndent=0),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.2, leading=10.2, textColor=GREY),
    "card_name": ParagraphStyle("card_name", fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=NAVY),
    "card": ParagraphStyle("card", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=4, alignment=TA_LEFT),
    "stamp": ParagraphStyle("stamp", fontName="Helvetica-Oblique", fontSize=7.8, leading=9.5, textColor=ORANGE),
    "speaker": ParagraphStyle("speaker", fontName="Helvetica", fontSize=11, leading=14.5, spaceAfter=7,
                              leftIndent=0),
    "box": ParagraphStyle("box", fontName="Helvetica", fontSize=8.3, leading=10, textColor=colors.white),
    "box_dark": ParagraphStyle("box_dark", fontName="Helvetica", fontSize=8.3, leading=10, textColor=colors.black),
}
SPEAKER_COLORS = {"Portfolio Manager Agent": "#c55a11", "Research Agent": "#1f4e79", "Analytics Agent": "#2e7d4f"}


def _p(text, style):
    """A Paragraph in one of `STYLES` (text is ReportLab mini-HTML; escape agent text with `_safe`)."""
    return Paragraph(text, STYLES[style])


def _safe(text):
    """Escape agent-written text for ReportLab's mini-HTML."""
    return escape(str(text))


# A correlation statement with its figure(s): "correlation with SPY of 0.16", "0.13 to 0.16 correlation to SPY",
# "correlations of 0.13-0.36". User requirement: correlation is highlighted wherever the deck explains benefits.
_CORR_RE = re.compile(
    r"(?:-?\d\.\d{2}(?:\s*(?:to|-|–)\s*-?\d\.\d{2})?\s+)?correlations?\b[^.;•]{0,40}?-?\d\.\d{2}"
    r"(?:\s*(?:to|-|–)\s*-?\d\.\d{2})?|-?\d\.\d{2}(?:\s*(?:to|-|–)\s*-?\d\.\d{2})?\s+correlations?\b(?:\s+(?:to|with)\s+\w+)?",
    re.IGNORECASE)


def _highlight(escaped):
    """Bold, navy correlation phrases in already-escaped agent text (see `_CORR_RE`)."""
    return _CORR_RE.sub(lambda m: f'<b><font color="#1f4e79">{m.group(0)}</font></b>', escaped)


def _no_negative_zero(s):
    """A tiny negative value rounds to "-0.0"; show it as "0.0"."""
    return s[1:] if s.startswith("-") and not any(ch in "123456789" for ch in s) else s


def pct(v, d=1):
    """Format a fraction as a percentage with `d` decimals ("n/a" for missing)."""
    return "n/a" if v is None or v != v else _no_negative_zero(f"{v * 100:.{d}f}") + "%"


def num(v, d=2):
    """Format a ratio with `d` decimals ("n/a" for missing)."""
    return "n/a" if v is None or v != v else _no_negative_zero(f"{v:.{d}f}")


@dataclass
class RunArtifacts:
    """The saved files of one run that the PDF is built from (see `load_run`)."""
    run_dir: Path
    deck: dict
    research: dict
    pm: dict
    dialogue: list
    analytics: dict
    team: dict
    manifest: dict
    returns: pd.DataFrame

    @property
    def scores(self):
        """Scores table (rows: ids, SPY, QQQ) as a DataFrame.

        Runs saved before the correlation column existed get it computed from their saved daily
        returns (the same window and definition as `ranking.score`), so older runs still rebuild.
        """
        sc = pd.DataFrame(self.research["scores"]).T
        if "corr_spy" not in sc.columns:
            sc["corr_spy"] = self.returns.drop(columns="rf", errors="ignore").corrwith(self.returns["SPY"])
        return sc

    @property
    def specs(self):
        """Strategy id -> spec dict (portfolio, sma, signal, lookback_days, label)."""
        return self.research["strategies"]

    @property
    def round1_ids(self):
        return self.research["rounds"]["1"]["ids"]

    def chart_data(self):
        """The `ChartData` bundle for re-rendering every chart."""
        return ChartData(self.returns, self.scores, self.specs, self.pm, self.analytics, self.round1_ids)


def load_run(run_dir):
    """Load every artifact the PDF needs from a finished run folder.

    Args:
        run_dir: a run folder inside the project.

    Returns:
        A `RunArtifacts`.

    Raises:
        FileNotFoundError: a required artifact is missing (the message names it).
    """
    run_dir = confine(run_dir)
    need = ("deck.json", "research.json", "pm.json", "dialogue.json", "analytics.json", "team.json",
            "strategy_returns.csv")
    missing = [n for n in need if not (run_dir / n).exists()]
    if missing:
        raise FileNotFoundError(f"{run_dir.name} is missing {missing}; the PDF can't be built from it.")
    manifest = read_json(run_dir / "manifest.json") if (run_dir / "manifest.json").exists() else {}
    returns = pd.read_csv(run_dir / "strategy_returns.csv", index_col=0, parse_dates=True)
    return RunArtifacts(run_dir, read_json(run_dir / "deck.json"), read_json(run_dir / "research.json"),
                        read_json(run_dir / "pm.json"), read_json(run_dir / "dialogue.json"),
                        read_json(run_dir / "analytics.json"), read_json(run_dir / "team.json"), manifest, returns)


def build_from_run(run_dir, out_name="presentation.pdf"):
    """Re-render every chart and the whole PDF from a run's saved artifacts. No agent or API call.

    Args:
        run_dir: a finished run folder (needs deck.json and the research/PM/analytics/team artifacts).
        out_name: output file name inside the run folder.

    Returns:
        The PDF path.

    Side effects:
        Overwrites charts/*.png and `out_name` in the run folder.
    """
    art = load_run(run_dir)
    data = art.chart_data()
    charts = {kind: render(kind, art.run_dir / "charts", data) for kind in art.deck.get("charts", [])}
    return Deck(art, charts).build(art.run_dir / out_name)


class Deck:
    """Assembles and draws the pages. Page order is fixed in `pages`; agent slides fill their sections."""

    def __init__(self, art, charts):
        self.art = art
        self.charts = charts
        self.cfg = RankingConfig(**{k: tuple(v) if isinstance(v, list) else v
                                    for k, v in art.manifest.get("strategy_params", {}).items()}) \
            if art.manifest.get("strategy_params") else RankingConfig()
        self.window = f"{art.returns.index.min().date()} to {art.returns.index.max().date()}"

    # ------------------------------------------------------------ page plan

    def _slides(self, section):
        return [("slide", s) for s in self.art.deck["slides"] if s["section"] == section]

    def pages(self):
        """The full page list as (kind, args), page 1 first. Tables appear exactly `MAX_TABLE_PAGES` times."""
        team = self.art.team["members"]
        return [
            ("title_page", {}), ("flowchart", {}), ("harness", {}), ("guardrails", {}),
            *self._slides("executive_summary"),
            ("meeting", {}),
            # Runs saved before the feedback pages existed have no feedback scripts; they rebuild without them.
            *[("feedback", {"kind": k}) for k in FEEDBACK_PAGES if k in self.art.pm.get("feedback", {})],
            *self._slides("strategy"),
            *self._slides("round1"),
            ("table_grid", {}),
            *self._slides("pm_selection"),
            ("decision_log", {"part": "selection"}),
            ("decision_log", {"part": "proposals"}),
            *self._slides("round2"),
            ("decision_log", {"part": "final"}),
            ("table_rounds", {}),
            *self._slides("risk"),
            *self._slides("diversification"),
            ("team", {"members": team[:3], "heading": "Meet the Digital Investment Team (AI-generated, fictional)"}),
            ("team", {"members": team[3:], "heading": "Digital Investment Team, continued (AI-generated, fictional)"}),
            ("disclosures", {}),
        ]

    PERFORMANCE_PAGES = {"table_grid", "table_rounds", "meeting", "feedback", "decision_log"}

    DOC_TITLE = TITLE

    def build(self, path):
        """Draw every page to `path` (confined to the project) and return it.

        `pages()` entries are ``(kind, args)`` or ``(kind, args, tag)``; a tag (e.g. "Appendix A: Research")
        is drawn in the top-right corner of that page.
        """
        path = confine(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
        c.setTitle(self.DOC_TITLE)
        c.setAuthor(AUTHOR)
        pages = self.pages()
        for i, (kind, args, *tag) in enumerate(pages, start=1):
            if kind == "slide":
                self._draw_slide(c, **args)
                perf = args.get("performance", False)
            else:
                getattr(self, f"_draw_{kind}")(c, **args)
                perf = kind in self.PERFORMANCE_PAGES
            if tag:   # inside the navy top band, clear of any page title
                c.setFont("Helvetica-Bold", 7)
                c.setFillColor(colors.white)
                c.drawRightString(PAGE_W - 0.6 * inch, PAGE_H - 0.125 * inch, tag[0].upper())
            self._footer(c, i, len(pages), perf)
            c.showPage()
        c.save()
        return path

    # ------------------------------------------------------------- helpers

    def _header(self, c, title):
        c.setFillColor(NAVY)
        c.rect(0, PAGE_H - 0.18 * inch, PAGE_W, 0.18 * inch, fill=1, stroke=0)
        w, h = PAGE_W - 1.2 * inch, 0.85 * inch
        f = Frame(0.6 * inch, PAGE_H - 1.15 * inch, w, h, showBoundary=0)
        # KeepInFrame shrinks a long title instead of letting the Frame silently drop it.
        f.addFromList([KeepInFrame(w, h, [_p(_safe(title), "title")], mode="shrink")], c)

    def _footer(self, c, page, total, performance):
        c.setStrokeColor(colors.HexColor("#d9d9d9"))
        c.line(0.6 * inch, 0.62 * inch, PAGE_W - 0.6 * inch, 0.62 * inch)
        f = Frame(0.6 * inch, 0.12 * inch, PAGE_W - 1.6 * inch, 0.48 * inch, showBoundary=0)
        f.addFromList([_p(PERF_FOOTER if performance else GEN_FOOTER, "small")], c)
        c.setFont("Helvetica", 8)
        c.setFillColor(GREY)
        c.drawRightString(PAGE_W - 0.6 * inch, 0.3 * inch, f"{page} / {total}")

    @staticmethod
    def _flow(c, x, y, w, h, flow):
        """Draw flowables in a box, shrinking them to fit (never silently dropping content)."""
        Frame(x, y, w, h, showBoundary=0, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0).addFromList(
            [KeepInFrame(w, h, flow, mode="shrink")], c)

    @staticmethod
    def _table(data, widths, font=8.6, pad=2.2, bold_rows=(), bold_cells=()):
        t = Table(data, colWidths=widths)
        style = [
            ("FONT", (0, 0), (-1, -1), "Helvetica", font), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", font),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9d9d9")),
            ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]
        style += [("FONT", (0, r), (-1, r), "Helvetica-Bold", font) for r in bold_rows]
        style += [("FONT", cell, cell, "Helvetica-Bold", font) for cell in bold_cells]
        style += [("TEXTCOLOR", cell, cell, NAVY) for cell in bold_cells]
        t.setStyle(TableStyle(style))
        return t

    def _label(self, sid):
        return self.art.specs[sid]["label"] if sid in self.art.specs else f"{sid} buy & hold"

    # ------------------------------------------------------------ code pages

    def _draw_title_page(self, c):
        """Page 1: the title, and how the agents ran the whole process, including the Research <-> PM loop."""
        c.setFillColor(NAVY)
        c.rect(0, PAGE_H - 2.55 * inch, PAGE_W, 2.55 * inch, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 27)
        c.drawString(0.6 * inch, PAGE_H - 0.95 * inch, TITLE)
        sub = ParagraphStyle("cover_sub", fontName="Helvetica", fontSize=13, leading=17, textColor=colors.white)
        self._flow(c, 0.6 * inch, PAGE_H - 1.85 * inch, PAGE_W - 1.2 * inch, 0.7 * inch, [Paragraph(_safe(SUBTITLE), sub)])
        c.setFillColor(ORANGE)
        c.rect(0.6 * inch, PAGE_H - 2.0 * inch, 1.2 * inch, 0.07 * inch, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica", 10)
        c.drawString(0.6 * inch, PAGE_H - 2.35 * inch, f"Prepared {date.today():%B %d, %Y}  |  Backtest window "
                     f"{self.window}  |  Hypothetical backtested results")
        self._about_columns(c, PAGE_H - 2.75 * inch, "presentation", "Pages 2-4 show")

    def _draw_about(self, c, doc="pitchbook", where="Appendix C shows"):
        """The deck's page-1 explanation of the agentic process, as a standalone page (used in the pitchbook)."""
        self._header(c, "How AI Agents Produced This Document")
        self._about_columns(c, PAGE_H - 1.3 * inch, doc, where)

    def _about_columns(self, c, top, doc, where):
        """Two columns: how the six agents produced the document, and the Research <-> PM back-and-forth.

        Args:
            top: y of the columns' top edge.
            doc: what to call the document ("presentation", "pitchbook").
            where: lead-in naming where the workflow and governance pages are ("Pages 2-4 show").
        """
        steps = self._loop_steps()
        self._about_body(c, top, doc, where, steps)

    def _loop_steps(self):
        """The Research <-> PM back-and-forth as four numbered steps (ReportLab mini-HTML), with this run's outcome."""
        pm, cfg = self.art.pm, self.cfg
        reps = pm["final"]["replacements"]
        swap = (f"{len(reps)} of the {cfg.n_proposals} new strategies beat the weakest of the top {cfg.top_n} and "
                f"replaced it" if reps else f"none of the {cfg.n_proposals} new strategies beat the weakest of the "
                f"top {cfg.top_n}, so the line-up was kept")
        steps = [
            f"<b>1. Research Agent, round 1.</b> Backtests all {len(self.art.round1_ids)} combinations of portfolio "
            "rule, ranking signal (the close or a 20/50/200-day moving average) and lookback, on the same dates, "
            "against SPY and QQQ buy & hold. It sends the Portfolio Manager its findings, with pros and cons.",
            f"<b>2. Portfolio Manager Agent, round 1.</b> Selects the top {cfg.top_n} by total return versus SPY "
            f"(ranking checked by code), explains each pick, and proposes {cfg.n_proposals} new parameter sets, such "
            "as adjusted lookbacks or moving averages, each with a hypothesis, a pro and a con.",
            "<b>3. Research Agent, round 2.</b> Runs the proposals on the same dates and reports back.",
            f"<b>4. Portfolio Manager Agent, round 2.</b> A new strategy that beats the weakest of the top "
            f"{cfg.top_n} replaces it: {swap}. The PM explains every final decision.",
        ]
        return steps

    def _about_body(self, c, top, doc, where, steps):
        """Draw the two about-columns (see `_about_columns`) given the loop steps."""
        left = [_p(f"How AI agents produced this {doc}", "h2"),
                _p("Six AI agents (Claude) ran the whole process, from downloading prices to writing these slides. "
                   "Code computes every number; agents decide what to examine, interpret the results and write. "
                   "A deterministic harness runs the agents in order and checks each one's work before the next "
                   "starts; hooks and guardrails police every tool call and every sentence.", "body"),
                _p("The other agents: the <b>Data Agent</b> prepares and checks prices; the <b>Analytics Agent</b> "
                   "measures risk, return and portfolio fit of the final line-up; the <b>Presentation Agent</b> "
                   f"writes the slides; the <b>Team Agent</b> creates the fictional team. {where} the "
                   "workflow, harness, hooks, guardrails and evals.", "body")]
        right = [_p("The Research and Portfolio Manager back-and-forth", "h2"), *[_p(s, "body") for s in steps],
                 _p("Their full exchange, with every rationale, pro and con, is in the decision log; a simulated "
                    "meeting between the agents summarizes it.", "small")]
        bottom, gap = 0.75 * inch, 0.35 * inch
        col = (PAGE_W - 1.2 * inch - gap) / 2
        self._flow(c, 0.6 * inch, bottom, col, top - bottom, left)
        self._flow(c, 0.6 * inch + col + gap, bottom, col, top - bottom, right)

    def _box(self, c, x, y, w, h, title, text, fill):
        """A rounded flowchart box with a bold title and a short description."""
        c.setFillColor(fill)
        c.roundRect(x, y, w, h, 6, fill=1, stroke=0)
        dark = fill in (LIGHT, colors.HexColor("#d9d9d9"))
        style = "box_dark" if dark else "box"
        self._flow(c, x + 0.08 * inch, y + 0.06 * inch, w - 0.16 * inch, h - 0.12 * inch,
                   [_p(f"<b>{_safe(title)}</b>", style), _p(_safe(text), style)])

    @staticmethod
    def _arrow(c, x1, y1, x2, y2, label=None, color=GREY, label_dx=0.0, label_dy=0.06):
        """A straight arrow from (x1, y1) to (x2, y2) with an optional label at its midpoint."""
        c.setStrokeColor(color)
        c.setFillColor(color)
        c.setLineWidth(1.4)
        c.line(x1, y1, x2, y2)
        dx, dy = x2 - x1, y2 - y1
        length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
        ux, uy = dx / length, dy / length
        size = 0.09 * inch
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - size * ux + size * 0.5 * uy, y2 - size * uy - size * 0.5 * ux)
        p.lineTo(x2 - size * ux - size * 0.5 * uy, y2 - size * uy + size * 0.5 * ux)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        if label:
            c.setFont("Helvetica-Oblique", 7.2)
            c.setFillColor(GREY)
            c.drawCentredString((x1 + x2) / 2 + label_dx * inch, (y1 + y2) / 2 + label_dy * inch, label)

    def _draw_flowchart(self, c, title="The Agentic Workflow"):
        """Page 2: the agentic workflow, the Research <-> PM loop, and where harness, hooks and evals act."""
        self._header(c, title)
        # Gaps wide enough for the arrow labels, which sit above each arrow (they overlapped the boxes at 0.5").
        w, h, gap = 1.92 * inch, 0.95 * inch, 0.68 * inch
        xs = [0.6 * inch + i * (w + gap) for i in range(4)]
        ya, yb, yc = 5.45 * inch, 3.55 * inch, 1.75 * inch
        n, k, top = len(self.art.round1_ids), self.cfg.n_proposals, self.cfg.top_n
        pm_fill = ORANGE
        row_a = [("Data Agent", "Fetches 7 ETFs + T-bill rate; quality checks; saves the dataset", NAVY),
                 ("Research Agent: round 1", f"Backtests all {n} strategies on the same dates; findings with pros and cons", NAVY),
                 ("Portfolio Manager: round 1", f"Top {top} by total return vs SPY; proposes {k} new parameter sets", pm_fill),
                 ("Research Agent: round 2", f"Runs the {k} proposals; compares them with the top {top}", NAVY)]
        row_b = [("PDF (build-pdf)", "Rendered by code from saved artifacts; rebuildable without agents", colors.HexColor("#d9d9d9")),
                 ("Presentation Agent", "Writes slides from verified results; code renders tables and pages", NAVY),
                 ("Analytics Agent", "Risk, return by period, correlations, SPY blend", NAVY),
                 ("Portfolio Manager: round 2", "Applies the replacement rule; explains every decision; writes the meeting", pm_fill)]
        for x, (t, d, f) in zip(xs, row_a):
            self._box(c, x, ya, w, h, t, d, f)
        for x, (t, d, f) in zip(xs, row_b):
            self._box(c, x, yb, w, h, t, d, f)
        mid_a, mid_b = ya + h / 2, yb + h / 2
        labels_a = ("prices", f"{n} results", "5 proposals")
        for i, lab in enumerate(labels_a):
            self._arrow(c, xs[i] + w, mid_a, xs[i + 1], mid_a, lab, label_dy=0.1)
        # The loop back from the PM to the Research Agent (round 1 -> round 2) is the core back-and-forth.
        self._arrow(c, xs[3] + w / 2, ya, xs[3] + w / 2, yb + h, "5 results + findings", color=ORANGE, label_dx=0.75)
        labels_b = ("deck.json", "metrics", "final 5")
        for i, lab in enumerate(labels_b):
            self._arrow(c, xs[i + 1], mid_b, xs[i] + w, mid_b, lab, label_dy=0.1)
        self._box(c, xs[1], yc, w, h * 0.85, "Team Agent (in parallel)", "Fictional, labelled team for the team pages", NAVY)
        self._arrow(c, xs[1] + w / 2, yc + h * 0.85, xs[1] + w / 2, yb)
        self._box(c, xs[0], yc, w, h * 0.85, "Evals",
                  f"Score the finished run and PDF: {len(governance.EVALS)} scorers, red-team, notebook cross-check",
                  colors.HexColor("#d9d9d9"))
        self._arrow(c, xs[0] + w / 2, yb, xs[0] + w / 2, yc + h * 0.85)
        # Harness and hooks span every stage.
        c.setFillColor(LIGHT)
        c.roundRect(xs[2], yc, xs[3] + w - xs[2], h * 0.85, 6, fill=1, stroke=0)
        self._flow(c, xs[2] + 0.1 * inch, yc + 0.06 * inch, xs[3] + w - xs[2] - 0.2 * inch, h * 0.85 - 0.12 * inch, [
            _p("<b>Harness and hooks around every stage</b>", "box_dark"),
            _p("Validator after each stage; pre-tool hooks deny deletes and out-of-project paths; a process audit "
               "hook blocks file deletion and outside access; every call traced with tokens and cost per tool.",
               "box_dark")])
        self._flow(c, 0.6 * inch, 0.75 * inch, PAGE_W - 1.2 * inch, 0.75 * inch, [_p(
            "Orange: the Portfolio Manager Agent. The orange arrow is the hand-back from the Portfolio Manager to the "
            "Research Agent: round-1 results and findings go to the PM, the PM's proposals go back, the Research "
            "Agent reruns, and the PM makes the final call. Each arrow is a saved artifact that the next stage's "
            "validator checks.", "small")])

    def _draw_harness(self, c):
        """Page 3: harness, hooks, and this run's cost per agent and per tool (from the manifest)."""
        self._header(c, "The Harness: Orchestration, Hooks and Cost Tracking")
        gap = 0.35 * inch
        col = (PAGE_W - 1.2 * inch - gap) / 2
        top, bottom = PAGE_H - 1.3 * inch, 0.75 * inch
        left = [_p("Harness", "h2")] + [_p(f"&bull; {_safe(t)}", "body") for t in governance.HARNESS]
        left += [_p("Hooks", "h2")] + [_p(f"<b>{_safe(k)}</b>: {_safe(v)}", "body") for k, v in governance.HOOKS.items()]
        self._flow(c, 0.6 * inch, bottom, col, top - bottom, left)
        m = self.art.manifest
        right = [_p("This run: tokens and cost", "h2")]
        if m.get("cost_usd") is not None and m.get("cost_by_tool"):
            tokens = sum(m["usage_tokens"].values())
            right.append(_p(f"Total {tokens:,} tokens, ${m['cost_usd']:.2f}, {m.get('seconds', 0):.0f} seconds, "
                            f"model {_safe(m.get('model', ''))}.", "body"))
            agents = sorted(m["cost_by_agent_usd"].items(), key=lambda kv: -kv[1])
            data = [["Agent", "Input tokens", "Output tokens", "Cost"]] + [
                [a, f"{sum(v for k, v in m['tokens_by_agent'][a].items() if k != 'output'):,}",
                 f"{m['tokens_by_agent'][a]['output']:,}", f"${cost:.3f}"] for a, cost in agents]
            right.append(self._table(data, [1.75 * inch, 0.9 * inch, 0.9 * inch, 0.65 * inch], font=8.2, pad=1.6))
            tools = list(m["cost_by_tool"].items())[:10]
            data = [["Cost owner (tool or context)", "Input tokens", "Output tokens", "Cost"]] + [
                [o, f"{r['input_tokens']:,}", f"{r['output_tokens']:,}", f"${r['cost_usd']:.3f}"] for o, r in tools]
            right += [_p("&nbsp;", "small"),
                      self._table(data, [1.75 * inch, 0.9 * inch, 0.9 * inch, 0.65 * inch], font=8.2, pad=1.6),
                      _p("Top 10 cost owners. Input tokens are attributed to the content each call re-read (a tool "
                         "owns its requests and results), output tokens to the blocks written; each share is priced "
                         "at that call's rates, so all owners together add up to the run total (the manifest lists every "
                         "owner).", "small")]
            denials = len((m.get("hooks") or {}).get("denials", []))
            right.append(_p(f"Hook denials this run: {denials}.", "small"))
        else:
            right.append(_p("Cost figures are added once the run's manifest is written (the harness re-renders this "
                            "page at the end of the run, or run build-pdf).", "body"))
        self._flow(c, 0.6 * inch + col + gap, bottom, col, top - bottom, right)

    def _draw_guardrails(self, c):
        """Page 4: guardrails and evals, from `strategy.governance`."""
        self._header(c, "Guardrails and Evals")
        gap = 0.35 * inch
        col = (PAGE_W - 1.2 * inch - gap) / 2
        top, bottom = PAGE_H - 1.3 * inch, 0.75 * inch
        left = [_p("Guardrails", "h2")] + [_p(f"<b>{_safe(k)}.</b> {_safe(v)}", "body") for k, v in governance.GUARDRAILS]
        right = [_p(f"Evals: {len(governance.EVALS)} scorers on every finished run", "h2")]
        right += [_p(f"<b>{_safe(k)}</b>: {_safe(v)}", "log") for k, v in governance.EVALS.items()]
        right += [_p("Other eval layers", "h2")] + [_p(f"&bull; {_safe(t)}", "log") for t in governance.OTHER_EVAL_LAYERS]
        self._flow(c, 0.6 * inch, bottom, col, top - bottom, left)
        self._flow(c, 0.6 * inch + col + gap, bottom, col, top - bottom, right)

    def _draw_slide(self, c, title, bullets, chart=None, performance=False, section=None):
        """An agent-written slide: bullets, with the chart on the right when there is one."""
        self._header(c, title)
        top, bottom = PAGE_H - 1.25 * inch, 0.8 * inch
        flow = [_p(_highlight(_safe(b)), "bullet" if chart else "bullet_wide") for b in bullets]
        for para in flow:
            para.bulletText = "•"
        if chart:
            text_w = 3.3 * inch
            self._flow(c, 0.6 * inch, bottom, text_w, top - bottom, flow)
            img_x, img_w = 0.6 * inch + text_w + 0.2 * inch, PAGE_W - 1.2 * inch - text_w - 0.2 * inch
            c.drawImage(str(self.charts[chart]), img_x, bottom, width=img_w, height=top - bottom,
                        preserveAspectRatio=True, anchor="c")
        else:
            self._flow(c, 0.6 * inch, bottom, PAGE_W - 1.2 * inch, top - bottom, flow)

    def _draw_meeting(self, c):
        """The one-page simulated meeting between the PM Agent and the analyst agents."""
        self._draw_script(c, "Strategy Meeting: Portfolio Manager, Research and Analytics Agents (simulated conversation)",
                          "Simulated conversation, written by the Portfolio Manager Agent from this run's verified "
                          "results. The speakers are AI agents, not people; every number was checked against the "
                          "backtest.", self.art.pm["meeting"])

    def _draw_feedback(self, c, kind):
        """A one-page simulated feedback session: the PM reviewing the analyst agents' work (constructive or harsh)."""
        title, stamp = FEEDBACK_PAGES[kind]
        self._draw_script(c, title, stamp, self.art.pm["feedback"][kind])

    def _draw_script(self, c, title, stamp, lines):
        """A page of speaker lines under a header, with the "simulated" stamp; correlation phrases highlighted."""
        self._header(c, title)
        flow = [_p(stamp, "stamp"), _p("&nbsp;", "small")]
        for line in lines:
            color = SPEAKER_COLORS.get(line["speaker"], "#222222")
            flow.append(_p(f'<font color="{color}"><b>{_safe(line["speaker"])}:</b></font> {_highlight(_safe(line["text"]))}',
                         "speaker"))
        self._flow(c, 0.6 * inch, 0.8 * inch, PAGE_W - 1.2 * inch, PAGE_H - 2.1 * inch, flow)

    # Decision-log pages. Round 1 is split over two pages (selection, then proposals): on one page the text had to
    # shrink to about 8pt (visual review).
    DECISION_LOG_TITLES = {
        "selection": "Decision Log, Round 1: Research Findings and the PM's Top 5",
        "proposals": "Decision Log, Round 1: The PM's Proposals to the Research Agent",
        "final": "Decision Log, Round 2: Proposal Results and the PM's Final Decisions",
    }

    def _pro_con(self, head, body, item):
        """One decision entry: bold heading, reasoning, then a green Pro and an orange Con."""
        return _p(f"{head} {_highlight(_safe(body))} <font color='#2e7d4f'><b>Pro:</b></font> {_highlight(_safe(item['pro']))} "
                  f"<font color='#c55a11'><b>Con:</b></font> {_safe(item['con'])}", "log")

    def _draw_decision_log(self, c, part):
        """One page of the Research <-> PM exchange: findings (pros/cons) and the PM's decisions with reasoning."""
        pm = self.art.pm
        self._header(c, self.DECISION_LOG_TITLES[part])
        if part == "proposals":
            left = [_p("Portfolio Manager to Research Agent", "h2"), _p(_safe(pm.get("message_to_research", "")), "log"),
                    _p("Each proposal adjusts a parameter of a strategy that worked; the Research Agent ran all of them "
                       "on the same dates as round 1.", "small")]
        else:
            research = self.art.research["rounds"]["1" if part == "selection" else "2"]
            left = [_p("Research Agent to Portfolio Manager", "h2"), _p(_safe(research["message"]), "log")]
            for f in research["findings"]:
                para = _p(_highlight(_safe(f)), "log")
                para.bulletText = "•"
                left.append(para)
        right = []
        if part == "selection":
            right.append(_p(f"PM: top {self.cfg.top_n} selected (by total return)", "h2"))
            for p in pm["top5"]:
                head = f"<b>{_safe(self._label(p['id']))}</b> ({pct(self.art.scores.at[p['id'], 'total_return'])}):"
                right.append(self._pro_con(head, p["rationale"], p))
        elif part == "proposals":
            right.append(_p(f"PM: {self.cfg.n_proposals} new parameter sets", "h2"))
            for p in pm["proposals"]:
                right.append(self._pro_con(f"<b>{_safe(p['label'])}</b>:", p["hypothesis"], p))
        else:
            final = pm["final"]
            right += [_p("PM: final decisions", "h2"), _p(_safe(final["message"]), "log")]
            tag = {"kept": ("#1f4e79", "KEPT"), "added": ("#2e7d4f", "ADDED"), "removed": ("#c55a11", "REMOVED")}
            order = {sid: i for i, sid in enumerate(final["final"])}
            for d in sorted(final["decisions"], key=lambda d: order.get(d["id"], 99)):
                color, word = tag[d["status"]]
                head = (f"<font color='{color}'><b>[{word}]</b></font> <b>{_safe(self._label(d['id']))}</b> "
                        f"({pct(self.art.scores.at[d['id'], 'total_return'])}):")
                right.append(self._pro_con(head, d["rationale"], d))
        gap = 0.3 * inch
        lw = (PAGE_W - 1.2 * inch - gap) * 0.42
        rw = PAGE_W - 1.2 * inch - gap - lw
        top, bottom = PAGE_H - 1.3 * inch, 0.75 * inch
        self._flow(c, 0.6 * inch, bottom, lw, top - bottom, left)
        self._flow(c, 0.6 * inch + lw + gap, bottom, rw, top - bottom, right)

    def _draw_table_grid(self, c):
        """Analysis table 1 of 2: every round-1 strategy's total return, max drawdown and correlation with SPY."""
        self._header(c, f"{TABLE_PAGE_PREFIX} 1 of 2: Round 1, All {len(self.art.round1_ids)} Strategies")
        sc, specs = self.art.scores, self.art.specs
        top5 = {p["id"] for p in self.art.pm["top5"]}
        rows = list(dict.fromkeys((specs[i]["portfolio"], specs[i]["signal"]) for i in self.art.round1_ids))
        lbs = sorted({specs[i]["lookback_days"] for i in self.art.round1_ids})
        cell = {(specs[i]["portfolio"], specs[i]["signal"], specs[i]["lookback_days"]): i for i in self.art.round1_ids}
        y = PAGE_H - 1.3 * inch
        # Three 13-row matrices share the page, so the font and padding are tighter than elsewhere.
        for metric, name, fmt in (("total_return", "Total return", pct), ("max_drawdown", "Max drawdown", pct),
                                  ("corr_spy", "Correlation with SPY", num)):
            data = [[f"{name} by lookback (days)"] + [str(d) for d in lbs]]
            bold = []
            for r, (port, sig) in enumerate(rows, start=1):
                row = [f"{port} | {sig}"]
                for j, d in enumerate(lbs, start=1):
                    sid = cell[(port, sig, d)]
                    row.append(fmt(sc.at[sid, metric]))
                    if sid in top5:
                        bold.append((j, r))
                data.append(row)
            t = self._table(data, [2.75 * inch] + [0.88 * inch] * len(lbs), font=7.4, pad=0.75, bold_cells=bold)
            tw, th = t.wrapOn(c, PAGE_W, PAGE_H)
            t.drawOn(c, (PAGE_W - tw) / 2, y - th)
            y -= th + 0.1 * inch
        spy, qqq = sc.loc["SPY"], sc.loc["QQQ"]
        self._flow(c, 0.6 * inch, 0.68 * inch, PAGE_W - 1.2 * inch, max(y - 0.68 * inch, 0.25 * inch), [_p(
            f"Common window {self.window}. Benchmarks: SPY total return {pct(spy['total_return'])}, max drawdown "
            f"{pct(spy['max_drawdown'])}; QQQ {pct(qqq['total_return'])}, {pct(qqq['max_drawdown'])}, correlation with SPY "
            f"{num(qqq['corr_spy'])}. Correlation is of daily returns. Bold: the round-1 top 5 by total return. Signal = the close or an N-day moving average; lookback = calendar days of % change "
            "ranked at each month end. No trading costs.", "small")])

    def _draw_table_rounds(self, c):
        """Analysis table 2 of 2: the PM's rounds, the final line-up by period, and portfolio fit."""
        self._header(c, f"{TABLE_PAGE_PREFIX} 2 of 2: Portfolio Manager Rounds and the Final Line-up")
        sc, pm, an = self.art.scores, self.art.pm, self.art.analytics
        final = pm["final"]["final"]
        removed = {r["removed"] for r in pm["final"]["replacements"]}
        head = ["Strategy", "Round", "Status", "Total return", "vs SPY", "Ann. return", "Max DD", "Volatility", "Sharpe",
                "Corr. SPY"]
        data, bold = [head], []
        entries = [(p["id"], "1: top 5") for p in pm["top5"]] + [(p["id"], "2: proposal") for p in pm["proposals"]]
        for r, (sid, rnd) in enumerate(entries, start=1):
            status = "Final" if sid in final else ("Replaced" if sid in removed else "Not selected")
            s = sc.loc[sid]
            data.append([self._label(sid), rnd, status, pct(s["total_return"]), pct(s["excess_vs_spy"]),
                         pct(s["cagr"]), pct(s["max_drawdown"]), pct(s["volatility"]), num(s["sharpe"]),
                         num(s["corr_spy"])])
            if sid in final:
                bold.append(r)
        for b in ("SPY", "QQQ"):
            s = sc.loc[b]
            data.append([f"{b} buy & hold", "benchmark", "", pct(s["total_return"]), pct(s["excess_vs_spy"]),
                         pct(s["cagr"]), pct(s["max_drawdown"]), pct(s["volatility"]), num(s["sharpe"]),
                         num(s["corr_spy"])])
        t1 = self._table(data, [2.3 * inch, 0.75 * inch, 0.8 * inch, 0.8 * inch, 0.75 * inch, 0.78 * inch, 0.7 * inch,
                                0.72 * inch, 0.55 * inch, 0.68 * inch], font=8.0, pad=1.4, bold_rows=bold)
        w = round(an["portfolio_fit"]["blend_weight"] * 100)
        wins = [k for k in ("1Y", "3Y", "5Y", "SI") if k in an["windows"]]
        head2 = ["Final line-up by period"] + [f"{k} {'total' if k == '1Y' else 'ann.'}" for k in wins] + \
                ["Corr. SPY", "Corr. TLT", f"{100 - w}/{w} blend ann.", "Blend max DD"]
        data2 = [head2]
        fit = an["portfolio_fit"]
        for sid in [*final, "SPY", "QQQ"]:
            per = [pct(an["windows"][k]["series"][sid]["cagr"]) for k in wins]
            if sid in final:
                extra = [num(fit["correlation"][sid]["SPY"]), num(fit["correlation"][sid]["TLT"]),
                         pct(fit["blends"][sid]["cagr"]), pct(fit["blends"][sid]["max_drawdown"])]
            elif sid == "SPY":
                extra = ["1.00", "", pct(fit["spy"]["cagr"]), pct(fit["spy"]["max_drawdown"])]
            else:
                # TLT correlation and the blend are measured for the final strategies and SPY only
                extra = [num(self.art.scores.at[sid, "corr_spy"]), "n/a", "n/a", "n/a"]
            data2.append([self._label(sid)] + per + extra)
        t2 = self._table(data2, [2.55 * inch] + [0.72 * inch] * len(wins) + [0.72 * inch, 0.72 * inch, 0.95 * inch,
                                                                              0.9 * inch], font=8.0, pad=1.4)
        y = PAGE_H - 1.3 * inch
        for t in (t1, t2):
            tw, th = t.wrapOn(c, PAGE_W, PAGE_H)
            t.drawOn(c, (PAGE_W - tw) / 2, y - th)
            y -= th + 0.16 * inch
        self._flow(c, 0.6 * inch, 0.68 * inch, PAGE_W - 1.2 * inch, max(y - 0.68 * inch, 0.25 * inch), [_p(
            f"Common window {self.window}; periods end on the last completed session. Bold rows: the final line-up. "
            f"\"vs SPY\" = total return minus SPY's. 1Y is a total return; longer periods are annualized; SI = the whole "
            f"window. Blend = {100 - w}% SPY + {w}% strategy, rebalanced daily; correlation and blend are measured for the "
            "final strategies and SPY. Sharpe uses the 13-week T-bill. No trading costs.", "small")])

    def _draw_team(self, c, members, heading):
        """Three fictional team member cards, each stamped with the fictional label."""
        self._header(c, heading)
        col_w, gap = (PAGE_W - 1.2 * inch - 0.5 * inch) / 3, 0.25 * inch
        top, bottom = PAGE_H - 1.3 * inch, 0.8 * inch
        for i, m in enumerate(members):
            x = 0.6 * inch + i * (col_w + gap)
            c.setFillColor(LIGHT)
            c.roundRect(x, bottom, col_w, top - bottom, 8, fill=1, stroke=0)
            certs = ", ".join(m["certifications"]) or "None"
            edu = "<br/>".join(f"{_safe(e['degree'])}, {_safe(e['field'])}, {_safe(e['institution'])} ({e['year']})"
                               for e in m["education"])
            exp = "<br/>".join(f"{_safe(e['title'])}, {_safe(e['firm'])} ({_safe(e['years'])})" for e in m["experience"])
            flow = [
                _p(_safe(m["name"]), "card_name"),
                _p(f"<b>{_safe(m['title'])}</b><br/>Focus: {_safe(m['focus'])}", "card"),
                _p(f"<b>Certifications:</b> {_safe(certs)} | <b>Experience:</b> {m['years_experience']} yrs", "card"),
                _p(f"<b>Education</b><br/>{edu}", "card"),
                _p(f"<b>Experience</b><br/>{exp}", "card"),
                _p(_safe(m["bio"]), "card"),
                _p(FICTIONAL_LABEL, "stamp"),
            ]
            pad = 0.14 * inch
            self._flow(c, x + pad, bottom + pad, col_w - 2 * pad, top - bottom - 2 * pad, flow)

    def _draw_disclosures(self, c):
        """The last page: important disclosures (code-owned)."""
        self._header(c, "Important Disclosures")
        tested = len(self.art.specs)
        text = [_p(d.format(tested=tested, rule=_safe(rule_text(self.cfg)), window=self.window), "body")
                for d in DISCLOSURES]
        self._flow(c, 0.6 * inch, 0.75 * inch, PAGE_W - 1.2 * inch, PAGE_H - 2.0 * inch, text)


def chart_path(run_dir, kind):
    """Where a chart PNG lives inside a run folder."""
    return confine(Path(run_dir) / "charts" / f"{kind}.png")
