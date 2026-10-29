"""The "Pitchbook": a short investor deck plus an appendix holding every other page of the presentation.

Built by code only, from the same saved run artifacts as the full presentation
(`pdf.load_run`): no agent or API call, so it can be rebuilt at any time with
``build-pitchbook runs/<id>``. The harness builds it at the end of every run.

Main section (in order):
 1. Cover.
 2. Summary: the top strategy and why it makes sense (diversification,
    correlation profile, macro basket, systematic rules, agentic workflow), with a
    balancing caveat.
 3. Performance: a growth chart and summary statistics (top strategy, its SPY
    blend, SPY, QQQ; by period).
 4. The team: the analysts, an org chart, and their actual investing experience (zero).
 5. Investment Process: the agentic workflow flowchart.
 6. Investment Process: the Portfolio Manager <-> analyst dialogue.
 7. Constructive Feedback and 8. Harsh Feedback (the PM's simulated reviews).
 9. Token counts and costs per tool (and per agent), from the run's manifest.
10. Evals, hooks, harness and guardrails on one page, with this run's activity.
11. Compliance (with clearly fictional "FAKEGIPS" and "FAKECFA" labels).
12. Disclosures: all fake, all agentic, no risk management, no guarantee.

Appendix: every presentation page not used above, grouped into lettered
sections (strategy and research, risk and portfolio fit, process and
governance, team, full disclosures) after a contents page. Every page that
reuses the presentation's drawing code is rendered identically.

All text here is code-owned. Its numbers come straight from the run's saved
results; agent-written text appears only where the presentation already
showed it (slides, dialogue, feedback), unchanged.
"""

from strategy import governance
from strategy.charts import render, render_tool_costs
from strategy.pdf import (FEEDBACK_PAGES, GREY, NAVY, ORANGE, PAGE_H, PAGE_W, SPEAKER_COLORS, Deck, _highlight, _p,
                          _safe, inch, load_run, num, pct)
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, TableStyle
from strategy.team import FICTIONAL_LABEL

PITCH_TITLE = "Agentic Capital Management Pitchbook"
PITCH_SUBTITLE = "A systematic, AI-run macro rotation strategy: summary, performance, team and process"

# Appendix sections in order: letter -> (name, page entries builder). See `Pitchbook.appendix`.
APPENDIX_SECTIONS = (
    ("A", "Strategy and Research"),
    ("B", "Risk and Portfolio Fit"),
    ("C", "Process and Governance"),
    ("D", "Investment Team"),
    ("E", "Full Disclosures"),
)

COMPLIANCE_BULLETS = [
    "<b>FAKEGIPS compliant*.</b> Performance is shown as a single hypothetical, backtested strategy against stated "
    "benchmarks (SPY and QQQ), with the methodology, the scoring window and the absence of fees and trading costs "
    "disclosed.",
    "<b>Adheres to the FAKECFA Code of Ethics*.</b> No promises of future returns, no misrepresentation of "
    "experience, conflicts and limitations disclosed, and every figure traceable to the computed results.",
    "<b>Every number is verified by code.</b> Agent-written text is rejected if it contains a figure that is not in "
    "the backtest results, at the precision written.",
    "<b>Language controls.</b> Promissory, risk-denying and urgency language (\"guaranteed\", \"can't lose\", "
    "\"act now\", \"eliminates risk\") is blocked before it reaches a page.",
    "<b>Labelled content.</b> Simulated conversations are labelled simulated; every team member is labelled an "
    "AI-generated fictional persona; disclosures are written by code, not agents.",
    "<b>Operational controls.</b> Hooks and a process sandbox stop any agent or code from deleting files or "
    "touching anything outside the project; every tool call is logged with its cost.",
]
COMPLIANCE_FOOTNOTE = (
    "*FAKEGIPS and FAKECFA are fictional standards invented for this demonstration. Agentic Capital Management is "
    "not a real firm, does not claim compliance with the Global Investment Performance Standards (GIPS), and has no "
    "affiliation with or endorsement from CFA Institute.")

PITCH_DISCLOSURES = [
    "<b>This is all fake.</b> Agentic Capital Management is not a real firm. The investment team are AI-generated "
    "fictional personas with invented careers, the conversations are simulated, and the \"FAKEGIPS\" and "
    "\"FAKECFA\" compliance labels are fictional. Nothing here is an offer, a solicitation or investment advice.",
    "<b>All of it is agentic.</b> Every step, from downloading prices and backtesting to choosing the strategy and "
    "writing the commentary, was performed by AI agents. No human investment professional reviewed or approved it.",
    "<b>Zero risk management is applied.</b> The strategy has no position limits, no stop-losses, no volatility "
    "targeting, no liquidity or capacity analysis, no trading costs, taxes or fees, and no human oversight. A Top 1 "
    "strategy holds 100% of capital in a single ETF.",
    "<b>Past results are no guarantee of future performance.</b> All results are hypothetical, backtested and "
    "in-sample: the strategy was selected because it did best among {tested} combinations tested on the same "
    "historical period ({window}), so its results benefit from hindsight and overstate what could have been "
    "expected in advance.",
    "<b>Investing involves risk, including loss of principal.</b> The ETFs involved include equities, long-dated "
    "Treasuries, gold, crude oil futures (USO) and high-yield credit (JNK), each of which can fall sharply. Data from "
    "Yahoo Finance via yfinance, not independently verified.",
]


def build_pitchbook_from_run(run_dir, out_name="pitchbook.pdf"):
    """Render the pitchbook from a finished run's saved artifacts. No agent or API call.

    Args:
        run_dir: a finished run folder (the same artifacts `pdf.build_from_run` needs).
        out_name: output file name inside the run folder.

    Returns:
        The PDF path.

    Side effects:
        Overwrites charts/*.png used by the pitchbook and `out_name` in the run folder.
    """
    art = load_run(run_dir)
    data = art.chart_data()
    kinds = sorted({*art.deck.get("charts", []), "pitch_performance"})
    charts = {kind: render(kind, art.run_dir / "charts", data) for kind in kinds}
    if art.manifest.get("cost_by_tool"):
        charts["tool_costs"] = render_tool_costs(art.run_dir / "charts", art.manifest["cost_by_tool"])
    return Pitchbook(art, charts).build(art.run_dir / out_name)


class Pitchbook(Deck):
    """The pitchbook: a short main section and a sorted appendix of every other presentation page."""

    DOC_TITLE = PITCH_TITLE
    PERFORMANCE_PAGES = Deck.PERFORMANCE_PAGES | {"pitch_summary", "pitch_performance", "pitch_dialogue"}

    # ------------------------------------------------------------ page plan

    def main(self):
        """The main section's pages, in order."""
        feedback = [("feedback", {"kind": k}) for k in FEEDBACK_PAGES if k in self.art.pm.get("feedback", {})]
        return [("pitch_cover", {}), ("pitch_summary", {}), ("pitch_performance", {}), ("pitch_team", {}),
                ("flowchart", {"title": "Investment Process"}), ("pitch_dialogue", {}), *feedback,
                ("pitch_costs", {}), ("pitch_governance", {}), ("pitch_compliance", {}), ("pitch_disclosures", {})]

    def appendix(self):
        """Every presentation page the main section doesn't use, grouped by section letter.

        Returns:
            A list of (letter, name, [(kind, args), ...]) in `APPENDIX_SECTIONS` order.
        """
        s = self._slides
        team = self.art.team["members"]
        groups = {
            "A": [*s("executive_summary"), *s("strategy"), *s("round1"), ("table_grid", {}), *s("pm_selection"),
                  ("decision_log", {"part": "selection"}), ("decision_log", {"part": "proposals"}), *s("round2"),
                  ("decision_log", {"part": "final"}), ("table_rounds", {})],
            "B": [*s("risk"), *s("diversification")],
            "C": [("about", {}), ("meeting", {}), ("harness", {}), ("guardrails", {})],
            "D": [("team", {"members": team[:3], "heading": "Meet the Digital Investment Team (AI-generated, fictional)"}),
                  ("team", {"members": team[3:], "heading": "Digital Investment Team, continued (AI-generated, fictional)"})],
            "E": [("disclosures", {})],
        }
        return [(letter, name, groups[letter]) for letter, name in APPENDIX_SECTIONS]

    def pages(self):
        """Main section, the appendix contents page, then each appendix page tagged with its section."""
        main = self.main()
        sections = self.appendix()
        first = len(main) + 2                      # page number of the first appendix content page
        contents, page = [], first
        for letter, name, entries in sections:
            contents.append((letter, name, page, page + len(entries) - 1))
            page += len(entries)
        tagged = [(kind, args, f"Appendix {letter}: {name}") for letter, name, entries in sections
                  for kind, args in entries]
        return [*main, ("appendix_contents", {"contents": contents}), *tagged]

    # ------------------------------------------------------------ helpers

    def _top(self):
        """The top strategy (best total return in the final line-up) and its scores row."""
        sid = self.art.pm["final"]["final"][0]
        return sid, self.art.scores.loc[sid]

    def _bullets(self, items, style="bullet_wide"):
        """Bulleted paragraphs (items are ReportLab mini-HTML)."""
        out = []
        for item in items:
            para = _p(item, style)
            para.bulletText = "•"
            out.append(para)
        return out

    # ------------------------------------------------------------ main pages

    def _draw_pitch_cover(self, c):
        """Cover: title, subtitle, date and window, and the top strategy in one line."""
        c.setFillColor(NAVY)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 34)
        c.drawString(0.8 * inch, 5.3 * inch, PITCH_TITLE)
        sub = ParagraphStyle("pitch_sub", fontName="Helvetica", fontSize=15, leading=19, textColor=colors.white)
        self._flow(c, 0.8 * inch, 4.3 * inch, PAGE_W - 1.6 * inch, 0.85 * inch, [Paragraph(_safe(PITCH_SUBTITLE), sub)])
        c.setFillColor(ORANGE)
        c.rect(0.8 * inch, 4.1 * inch, 1.2 * inch, 0.08 * inch, fill=1, stroke=0)
        sid, _ = self._top()
        c.setFillColor(colors.white)
        c.setFont("Helvetica", 11)
        c.drawString(0.8 * inch, 3.65 * inch, f"Top strategy: {self._label(sid)}  |  Backtest window {self.window}")
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(0.8 * inch, 0.6 * inch, "Hypothetical backtested results. Entirely fictional and AI-generated: "
                     "see the disclosures. Not an offer or solicitation.")

    def _draw_pitch_summary(self, c):
        """The top strategy and why it makes sense, from the run's computed results."""
        sid, s = self._top()
        spec = self.art.specs[sid]
        sc, fit = self.art.scores, self.art.analytics["portfolio_fit"]
        blend, spy_fit = fit["blends"][sid], fit["spy"]
        corr = fit["correlation"][sid]
        w = round(fit["blend_weight"] * 100)
        led = self.art.research.get("facts", {}).get("leader_share", {}).get(sid, {})
        led_text = (", ".join(f"{t} {v * 100:.0f}%" for t, v in sorted(led.items(), key=lambda kv: -kv[1])[:4])
                    if led else "")
        signal = "close" if spec["sma"] == 0 else f"{spec['sma']}-day moving average"
        self._header(c, f"The Top Strategy: {self._label(sid)}")
        items = [
            f"<b>What it is.</b> At each month end, rank seven ETFs (US large caps, the Nasdaq-100, long and "
            f"intermediate Treasuries, gold, oil and high-yield credit) by the % change of their {signal} over "
            f"{spec['lookback_days']} days, and hold the leader for the month.",
            f"<b>Returns.</b> {pct(s['total_return'])} total return ({pct(s['cagr'])} a year) against "
            f"{pct(sc.at['SPY', 'total_return'])} for SPY and {pct(sc.at['QQQ', 'total_return'])} for QQQ, "
            f"{self.window}.",
            f"<b>Correlation profile.</b> A correlation with SPY of {num(corr['SPY'])}, versus {num(sc.at['QQQ', 'corr_spy'])} "
            f"for QQQ; correlation with TLT of {num(corr['TLT'])} and with GLD of {num(corr['GLD'])}.",
            "<b>Macro.</b> It rotates across a macro basket of stocks, bonds, gold, oil and credit, following whichever "
            "asset class is trending" + (f"; months led: {led_text}." if led_text else "."),
            f"<b>Diversification.</b> As a {w}% sleeve next to SPY: {pct(blend['cagr'])} a year vs {pct(spy_fit['cagr'])}, "
            f"volatility {pct(blend['volatility'])} vs {pct(spy_fit['volatility'])}, max drawdown "
            f"{pct(blend['max_drawdown'])} vs {pct(spy_fit['max_drawdown'])}.",
            "<b>Systematic and agentic.</b> Fixed rules, no discretion, rebalanced monthly; selected by six AI agents in "
            f"a two-round Research and Portfolio Manager loop from {len(self.art.specs)} tested strategies, with every "
            "number checked by code.",
            f"<b>The trade-off.</b> Volatility of {pct(s['volatility'])} and a max drawdown of {pct(s['max_drawdown'])} "
            f"(SPY: {pct(sc.at['SPY', 'volatility'])}, {pct(sc.at['SPY', 'max_drawdown'])}); chosen with hindsight; no "
            "trading costs.",
        ]
        flow = self._bullets([_highlight(t) for t in items], "bullet_wide")   # shrinks to fit if a run's text is long
        self._flow(c, 0.6 * inch, 0.8 * inch, PAGE_W - 1.2 * inch, PAGE_H - 2.1 * inch, flow)

    def _draw_pitch_performance(self, c):
        """Growth chart plus summary statistics: top strategy, SPY blend, SPY and QQQ, overall and by period."""
        sid, _ = self._top()
        sc, an = self.art.scores, self.art.analytics
        fit = an["portfolio_fit"]
        w = round(fit["blend_weight"] * 100)
        self._header(c, "Performance: Top Strategy vs SPY, QQQ and an 80/20 Blend" if w == 20 else
                     "Performance: Top Strategy vs SPY, QQQ and a SPY Blend")
        top, bottom = PAGE_H - 1.25 * inch, 0.8 * inch
        chart_w = 5.0 * inch          # leaves the statistics table room for seven columns (headers overlapped at 5.6")
        c.drawImage(str(self.charts["pitch_performance"]), 0.6 * inch, bottom + 1.0 * inch, width=chart_w,
                    height=top - bottom - 1.0 * inch, preserveAspectRatio=True, anchor="c")
        wins = [k for k in ("1Y", "3Y", "5Y", "SI") if k in an["windows"]]
        b = fit["blends"][sid]
        rows = [
            ("Top strategy", sc.loc[sid], sid),
            (f"{100 - w}/{w} SPY blend", {"total_return": b["total_return"], "cagr": b["cagr"],
                                         "volatility": b["volatility"], "max_drawdown": b["max_drawdown"],
                                         "sharpe": b["sharpe"], "corr_spy": b["correlation"]}, None),
            ("SPY", sc.loc["SPY"], "SPY"),
            ("QQQ", sc.loc["QQQ"], "QQQ"),
        ]
        stats = [["", "Total", "Annual", "Vol.", "Max DD", "Sharpe", "Corr. SPY"]] + [
            [name, pct(r["total_return"]), pct(r["cagr"]), pct(r["volatility"]), pct(r["max_drawdown"]),
             num(r["sharpe"]), num(r["corr_spy"])] for name, r, _ in rows]
        periods = [["Annual return"] + [("1Y total" if k == "1Y" else k) for k in wins]] + [
            [name] + [pct(an["windows"][k]["series"][key]["cagr"]) for k in wins]
            for name, _, key in rows if key]
        x = 0.6 * inch + chart_w + 0.2 * inch
        width = PAGE_W - 0.6 * inch - x
        t1 = self._table(stats, [1.05 * inch] + [(width - 1.05 * inch) / 6] * 6, font=7.8, pad=2.4, bold_rows=(1,))
        t2 = self._table(periods, [1.05 * inch] + [(width - 1.05 * inch) / len(wins)] * len(wins), font=7.8, pad=2.4,
                         bold_rows=(1,))
        y = top - 0.1 * inch
        for t in (t1, t2):
            tw, th = t.wrapOn(c, width, PAGE_H)
            t.drawOn(c, x, y - th)
            y -= th + 0.25 * inch
        self._flow(c, x, bottom, width, max(y - bottom, 0.3 * inch), [_p(
            f"Top strategy: {_safe(self._label(sid))}. Window {self.window}; 1Y is a total return, longer periods are "
            f"annualized; SI = the whole window. The blend is {100 - w}% SPY + {w}% strategy, rebalanced daily. "
            "Sharpe uses the 13-week T-bill. Hypothetical; no trading costs.", "small")])

    def _draw_pitch_team(self, c):
        """The analysts in an org chart, and their actual investing experience: zero years."""
        self._header(c, "The Team: Analysts and Organization")
        members = self.art.team["members"]
        pm = next(m for m in members if m["role"] == "Portfolio Manager")
        analysts = [m for m in members if m is not pm]
        bw, bh = 1.75 * inch, 0.95 * inch
        top_y = PAGE_H - 2.35 * inch
        cx = PAGE_W / 2
        self._box(c, cx - bw / 2, top_y, bw, bh, f"{pm['name']}", f"{pm['title']} (Portfolio Manager)", ORANGE)
        gap = (PAGE_W - 1.2 * inch - len(analysts) * bw) / max(len(analysts) - 1, 1)
        row_y = top_y - 1.55 * inch
        c.setStrokeColor(GREY)
        c.setLineWidth(1.2)
        mid_y = top_y - 0.35 * inch
        c.line(cx, top_y, cx, mid_y)
        xs = [0.6 * inch + i * (bw + gap) for i in range(len(analysts))]
        c.line(xs[0] + bw / 2, mid_y, xs[-1] + bw / 2, mid_y)
        for x, m in zip(xs, analysts):
            c.line(x + bw / 2, mid_y, x + bw / 2, row_y + bh)
            self._box(c, x, row_y, bw, bh, m["name"], m["focus"], NAVY)
        stated = sum(m["years_experience"] for m in members)
        note_top = row_y - 0.25 * inch
        flow = [
            _p(f"<font color='#c55a11'><b>Combined real-world investing experience: 0 years.</b></font> The six "
               f"résumés above add up to {stated} years of stated experience, every year of it invented. These are "
               f"{FICTIONAL_LABEL}s; the actual work, from data to decisions to this document, was done by six AI "
               "agents.", "body_big"),
            _p("The analysts' focus areas mirror the agents that did the work: research and signal design, risk, macro "
               "and cross-asset, data and backtest integrity, and execution and communications. Full profiles are in "
               "Appendix D.", "body"),
        ]
        self._flow(c, 0.6 * inch, 0.8 * inch, PAGE_W - 1.2 * inch, note_top - 0.8 * inch, flow)

    def _draw_pitch_dialogue(self, c):
        """Investment Process: the four messages between the Research Agent (the analyst) and the Portfolio Manager."""
        self._header(c, "Investment Process: Portfolio Manager and Analyst Dialogue")
        flow = [_p("The real messages exchanged in this run, written by the agents and number-checked by code. The full "
                   "decision log, with every pick, proposal and decision, is in Appendix A.", "stamp"),
                _p("&nbsp;", "small")]
        for msg in self.art.dialogue:
            color = SPEAKER_COLORS.get(msg["from"], "#222222")
            stage = f"round {msg['round']}"
            flow.append(_p(f'<font color="{color}"><b>{_safe(msg["from"])} to {_safe(msg["to"])}</b></font> '
                           f'<font color="#595959">({stage})</font>: {_highlight(_safe(msg["text"]))}', "speaker"))
        self._flow(c, 0.6 * inch, 0.8 * inch, PAGE_W - 1.2 * inch, PAGE_H - 2.1 * inch, flow)

    def _draw_pitch_costs(self, c):
        """Token counts and costs per tool and per agent, from the run's manifest (attribution sums to the total)."""
        self._header(c, "Token Counts and Costs per Tool")
        m = self.art.manifest
        if not m.get("cost_by_tool"):
            self._flow(c, 0.6 * inch, 0.8 * inch, PAGE_W - 1.2 * inch, PAGE_H - 2.1 * inch, [_p(
                "Costs are recorded in the run's manifest when the run finishes; rebuild the pitchbook after the run "
                "(build-pitchbook) to fill in this page.", "body_big")])
            return
        top, bottom = PAGE_H - 1.25 * inch, 0.8 * inch
        chart_w = 4.4 * inch
        c.drawImage(str(self.charts["tool_costs"]), 0.6 * inch, bottom, width=chart_w, height=top - bottom,
                    preserveAspectRatio=True, anchor="c")
        calls = {}
        for per_agent in m.get("tool_calls", {}).values():
            for tool, n in per_agent.items():
                calls[tool] = calls.get(tool, 0) + n["calls"]
        owners = list(m["cost_by_tool"].items())          # most expensive first
        shown, rest = owners[:10], owners[10:]           # same split as the chart (render_tool_costs, top=10)
        data = [["Tool or context", "Calls", "Input tokens", "Output tokens", "Cost"]]
        data += [[o, str(calls.get(o, "")), f"{r['input_tokens']:,}", f"{r['output_tokens']:,}", f"${r['cost_usd']:.3f}"]
                 for o, r in shown]
        if rest:
            data.append([f"{len(rest)} other tools", str(sum(calls.get(o, 0) for o, _ in rest)),
                         f"{sum(r['input_tokens'] for _, r in rest):,}", f"{sum(r['output_tokens'] for _, r in rest):,}",
                         f"${sum(r['cost_usd'] for _, r in rest):.3f}"])
        tokens = m["usage_tokens"]
        data.append(["Total", str(sum(calls.values())), f"{tokens['input'] + tokens['cache_write'] + tokens['cache_read']:,}",
                     f"{tokens['output']:,}", f"${m['cost_usd']:.3f}"])
        x = 0.6 * inch + chart_w + 0.2 * inch
        width = PAGE_W - 0.6 * inch - x
        t1 = self._table(data, [1.95 * inch] + [(width - 1.95 * inch) / 4] * 4, font=7.6, pad=1.6,
                         bold_rows=(len(data) - 1,))
        agents = sorted(m["cost_by_agent_usd"].items(), key=lambda kv: -kv[1])
        data2 = [["Agent", "Model input", "Output", "Cost"]] + [
            [a, f"{sum(v for k, v in m['tokens_by_agent'][a].items() if k != 'output'):,}",
             f"{m['tokens_by_agent'][a]['output']:,}", f"${cost:.3f}"] for a, cost in agents]
        t2 = self._table(data2, [1.95 * inch] + [(width - 1.95 * inch) / 3] * 3, font=7.6, pad=1.6)
        y = top
        for t in (t1, t2):
            tw, th = t.wrapOn(c, width, PAGE_H)
            t.drawOn(c, x, y - th)
            y -= th + 0.18 * inch
        self._flow(c, x, bottom, width, max(y - bottom, 0.3 * inch), [_p(
            f"This run: {sum(tokens.values()):,} tokens, ${m['cost_usd']:.2f}, {m.get('seconds', 0):.0f} seconds, model "
            f"{_safe(m.get('model', ''))}. Each model call's input tokens are attributed to the content it re-read (a tool "
            "owns its requests and results) and its output tokens to the blocks it wrote, priced at that call's rates, "
            "so the rows add up exactly to the total. Input includes cache reads (billed at 1/20 of the input price) "
            "and cache writes (1.25x).",
            "small")])

    def _draw_pitch_governance(self, c):
        """Evals, hooks, harness and guardrails on one page (full versions in Appendix C), with this run's activity."""
        self._header(c, "Evals, Hooks, Harness and Guardrails")
        m = self.art.manifest
        calls = sum(n["calls"] for per in m.get("tool_calls", {}).values() for n in per.values())
        errors = sum(n["errors"] for per in m.get("tool_calls", {}).values() for n in per.values())
        denials = len((m.get("hooks") or {}).get("denials", []))
        from strategy.cli import STAGE_NAMES      # the harness's stages (cli keeps the list import-light)
        stages = len(STAGE_NAMES)
        strip = (f"This run: {calls} tool calls through the hooks, {denials} hook denials, {errors} tool calls rejected "
                 f"and corrected by the agents, {stages} stages validated." if m.get("tool_calls") else
                 "Run activity is recorded in the manifest when the run finishes.")
        evals = ", ".join(governance.EVALS)
        panels = [
            ("Harness", [f"&bull; {_safe(t)}" for t in governance.HARNESS]),
            ("Hooks", [f"<b>{_safe(k)}</b>: {_safe(v)}" for k, v in governance.HOOKS.items()]),
            ("Guardrails", [f"<b>{_safe(k)}.</b> {_safe(v.split('. ')[0].rstrip('.'))}." for k, v in governance.GUARDRAILS]),
            (f"Evals: {len(governance.EVALS)} scorers on every run",
             [_safe(evals) + "."] + [f"&bull; {_safe(t)}" for t in governance.OTHER_EVAL_LAYERS]),
        ]
        top, bottom, gap = PAGE_H - 1.6 * inch, 0.8 * inch, 0.25 * inch
        self._flow(c, 0.6 * inch, top, PAGE_W - 1.2 * inch, 0.32 * inch, [_p(f"<b>{strip}</b>", "body")])
        cw, ch = (PAGE_W - 1.2 * inch - gap) / 2, (top - 0.1 * inch - bottom - gap) / 2
        for i, (title, items) in enumerate(panels):
            x = 0.6 * inch + (i % 2) * (cw + gap)
            y = bottom + (1 - i // 2) * (ch + gap)
            c.setFillColor(colors.HexColor("#eef3f8"))
            c.roundRect(x, y, cw, ch, 6, fill=1, stroke=0)
            pad = 0.12 * inch
            self._flow(c, x + pad, y + pad, cw - 2 * pad, ch - 2 * pad,
                       [_p(_safe(title), "h2"), *[_p(t, "log") for t in items]])

    def _draw_pitch_compliance(self, c):
        """Compliance bullets, with the fictional-standards footnote on the same page."""
        self._header(c, "Compliance")
        flow = self._bullets(COMPLIANCE_BULLETS, "bullet") + [_p("&nbsp;", "small"), _p(COMPLIANCE_FOOTNOTE, "body")]
        self._flow(c, 0.6 * inch, 0.8 * inch, PAGE_W - 1.2 * inch, PAGE_H - 2.1 * inch, flow)

    def _draw_pitch_disclosures(self, c):
        """Disclosures: all fake, all agentic, no risk management, no guarantee."""
        self._header(c, "Disclosures")
        items = [d.format(tested=len(self.art.specs), window=self.window) for d in PITCH_DISCLOSURES]
        self._flow(c, 0.6 * inch, 0.8 * inch, PAGE_W - 1.2 * inch, PAGE_H - 2.1 * inch, self._bullets(items, "bullet"))

    def _draw_appendix_contents(self, c, contents):
        """The appendix divider and contents: each section with its page range."""
        self._header(c, "Appendix")
        data = [["Section", "Contents", "Pages"]]
        descriptions = {
            "A": "Executive summary, strategy, round 1, analysis table 1, PM selection and proposals, decision log, "
                 "round 2, analysis table 2",
            "B": "Risk slides and the diversification section",
            "C": "How the agents produced the document, the strategy meeting, harness, hooks, guardrails and evals",
            "D": "Full profiles of the fictional investment team",
            "E": "The full presentation's important disclosures",
        }
        for letter, name, first, last in contents:
            data.append([f"{letter}. {name}", _p(descriptions[letter], "body"),
                         f"{first}-{last}" if last > first else str(first)])
        t = self._table(data, [2.4 * inch, 5.6 * inch, 0.9 * inch], font=10, pad=6)
        t.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "LEFT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        tw, th = t.wrapOn(c, PAGE_W, PAGE_H)
        t.drawOn(c, (PAGE_W - tw) / 2, PAGE_H - 1.5 * inch - th)
        self._flow(c, 0.6 * inch, 0.8 * inch, PAGE_W - 1.2 * inch, 0.6 * inch, [_p(
            "The appendix holds every page of the full presentation not used in the main section, unchanged.", "small")])
