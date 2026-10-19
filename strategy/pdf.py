"""Landscape slide-deck PDF (ReportLab).

The builder, not any agent, owns compliance content:
- every slide flagged `performance` gets the hypothetical-performance footer
- the metrics tables are rendered from analytics.json directly
- the all-MA comparison is always labeled IN-SAMPLE
- every team member card is stamped as an AI-generated fictional persona
- a full disclosures page is always appended
"""

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Frame, KeepInFrame, Paragraph, Table, TableStyle
from reportlab.pdfgen import canvas
from xml.sax.saxutils import escape

from strategy.paths import confine
from strategy.team import FICTIONAL_LABEL

PAGE_W, PAGE_H = landscape(letter)
NAVY = colors.HexColor("#1f4e79")
ORANGE = colors.HexColor("#c55a11")
GREY = colors.HexColor("#595959")
LIGHT = colors.HexColor("#eef3f8")

PERF_FOOTER = ("Hypothetical backtested performance, net of modeled trading costs, not of fees. "
               "Not actual trading. Past performance does not guarantee future results. See Important Disclosures.")
GEN_FOOTER = "For discussion purposes only. Not an offer or solicitation."

DISCLOSURES = [
    "<b>Hypothetical performance.</b> All performance shown is hypothetical and backtested. It does not "
    "represent actual trading or actual client accounts. Backtested results are prepared with the benefit of "
    "hindsight and have inherent limitations. No representation is made that any account will or is likely "
    "to achieve similar results.",
    "<b>Methodology.</b> The strategy holds either SPY or IEF, based on whether SPY closed above a moving "
    "average the previous day. The moving average (5, 20, 50 or 200 days) is chosen each January using only "
    "data available before that date (walk-forward). Results include a modeled trading cost of {cost} basis "
    "points per full switch between SPY and IEF. They exclude management fees, taxes and market impact beyond "
    "that assumption, and use adjusted closing prices, which include dividends. Partial calendar years are "
    "year-to-date.",
    "<b>In-sample results.</b> Comparisons of individual moving-average rules over the full period are "
    "in-sample. They are shown for context only, and overstate what an investor could have known in advance.",
    "<b>Risk.</b> Investing involves risk, including loss of principal. Trend-following signals can lag "
    "reversals, cause frequent switching in choppy markets, and underperform buy-and-hold for long periods. "
    "Treasury ETFs carry interest-rate risk and can fall alongside equities.",
    "<b>Data.</b> Prices from Yahoo Finance via the yfinance library. The data has not been independently "
    "verified. The risk-free rate is the 13-week Treasury bill yield (^IRX).",
    f"<b>Investment team.</b> The investment team members in this presentation are {FICTIONAL_LABEL}s "
    "created by an AI system for illustration. They are not real people, and their stated employers are "
    "fictional.",
    "<b>Not advice.</b> This presentation was produced by an automated multi-agent research prototype. It is "
    "for informational purposes only, and is not investment advice, an offer, or a solicitation to buy or "
    "sell any security.",
]

STYLES = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=NAVY),
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=12.5, leading=17, leftIndent=14,
                             bulletIndent=0, spaceAfter=7, textColor=colors.HexColor("#222222")),
    "bullet_wide": ParagraphStyle("bullet_wide", fontName="Helvetica", fontSize=16, leading=22, leftIndent=18,
                                  bulletIndent=0, spaceAfter=14, textColor=colors.HexColor("#222222")),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10.5, leading=14, spaceAfter=7),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.2, leading=10.2, textColor=GREY),
    "card_name": ParagraphStyle("card_name", fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=NAVY),
    "card": ParagraphStyle("card", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=4, alignment=TA_LEFT),
    "stamp": ParagraphStyle("stamp", fontName="Helvetica-Oblique", fontSize=7.8, leading=9.5, textColor=ORANGE),
}


def _p(text, style):
    return Paragraph(text, STYLES[style])


def _safe(text):
    return escape(str(text))


def pct(v, d=1):
    return "n/a" if v is None or v != v else f"{v * 100:.{d}f}%"


def num(v, d=2):
    return "n/a" if v is None or v != v else f"{v:.{d}f}"


class Deck:
    def __init__(self, title, subtitle, cost_bps=5.0):
        self.title = title
        self.subtitle = subtitle
        self.cost_bps = cost_bps
        self.pages = []

    # ------------------------------------------------------------- page types

    def add_slide(self, title, bullets, chart=None, performance=False):
        self.pages.append(("slide", dict(title=title, bullets=bullets, chart=chart, performance=performance)))

    def add_metrics_table(self, analytics):
        self.pages.append(("metrics", dict(analytics=analytics)))

    def add_candidates_table(self, candidates, history, period=None):
        self.pages.append(("candidates", dict(candidates=candidates, history=history, period=period)))

    def add_supporting_data(self, analytics):
        self.pages.append(("supporting", dict(analytics=analytics)))

    def add_team(self, team):
        members = team["members"]
        self.pages.append(("team", dict(members=members[:3], heading="Meet the Digital Investment Team")))
        self.pages.append(("team", dict(members=members[3:], heading="Meet the Digital Investment Team (continued)")))

    # ------------------------------------------------------------------ build

    def build(self, path):
        path = confine(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
        c.setTitle(self.title)
        c.setAuthor("SPY/IEF strategy pipeline (AI-generated)")
        self._cover(c)
        total = len(self.pages) + 2
        for i, (kind, args) in enumerate(self.pages, start=2):
            getattr(self, f"_draw_{kind}")(c, **args)
            perf = args.get("performance", kind in ("metrics", "candidates", "supporting"))
            self._footer(c, i, total, perf)
            c.showPage()
        self._disclosures(c)
        self._footer(c, total, total, False)
        c.showPage()
        c.save()
        return path

    def _header(self, c, title):
        c.setFillColor(NAVY)
        c.rect(0, PAGE_H - 0.18 * inch, PAGE_W, 0.18 * inch, fill=1, stroke=0)
        f = Frame(0.6 * inch, PAGE_H - 1.15 * inch, PAGE_W - 1.2 * inch, 0.85 * inch, showBoundary=0)
        f.addFromList([_p(_safe(title), "title")], c)

    def _footer(self, c, page, total, performance):
        c.setStrokeColor(colors.HexColor("#d9d9d9"))
        c.line(0.6 * inch, 0.62 * inch, PAGE_W - 0.6 * inch, 0.62 * inch)
        f = Frame(0.6 * inch, 0.12 * inch, PAGE_W - 1.6 * inch, 0.48 * inch, showBoundary=0)
        f.addFromList([_p(PERF_FOOTER if performance else GEN_FOOTER, "small")], c)
        c.setFont("Helvetica", 8)
        c.setFillColor(GREY)
        c.drawRightString(PAGE_W - 0.6 * inch, 0.3 * inch, f"{page} / {total}")

    def _cover(self, c):
        c.setFillColor(NAVY)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        c.setFillColor(ORANGE)
        c.rect(0.8 * inch, 4.35 * inch, 1.2 * inch, 0.08 * inch, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 34)
        c.drawString(0.8 * inch, 5.0 * inch, self.title)
        c.setFont("Helvetica", 16)
        c.drawString(0.8 * inch, 4.6 * inch, self.subtitle)
        c.setFont("Helvetica", 11)
        c.drawString(0.8 * inch, 3.9 * inch, f"Prepared {date.today():%B %d, %Y}")
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(0.8 * inch, 0.6 * inch, "Hypothetical backtested results. For discussion purposes only. "
                     "Generated by an AI multi-agent research pipeline.")
        c.showPage()

    def _draw_slide(self, c, title, bullets, chart, performance):
        self._header(c, title)
        top, bottom = PAGE_H - 1.25 * inch, 0.8 * inch
        flow = [_p(_safe(b), "bullet" if chart else "bullet_wide") for b in bullets]
        for para in flow:
            para.bulletText = "•"
        if chart:
            text_w = 3.3 * inch
            Frame(0.6 * inch, bottom, text_w, top - bottom, showBoundary=0).addFromList(
                [KeepInFrame(text_w, top - bottom, flow, mode="shrink")], c)
            img_x, img_w = 0.6 * inch + text_w + 0.2 * inch, PAGE_W - 1.2 * inch - text_w - 0.2 * inch
            c.drawImage(str(chart), img_x, bottom, width=img_w, height=top - bottom,
                        preserveAspectRatio=True, anchor="c")
        else:
            w = PAGE_W - 1.2 * inch
            Frame(0.6 * inch, bottom, w, top - bottom, showBoundary=0).addFromList(
                [KeepInFrame(w, top - bottom, flow, mode="shrink")], c)

    def _table(self, c, data, col_widths, y_top, highlight_rows=(), padding=3.5):
        t = Table(data, colWidths=col_widths)
        style = [
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9.5),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9d9d9")),
            ("TOPPADDING", (0, 0), (-1, -1), padding), ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ]
        for r in highlight_rows:
            style.append(("FONT", (0, r), (-1, r), "Helvetica-Bold", 9.5))
        t.setStyle(TableStyle(style))
        w, h = t.wrapOn(c, PAGE_W, PAGE_H)
        t.drawOn(c, (PAGE_W - w) / 2, y_top - h)
        return h

    def _draw_metrics(self, c, analytics):
        self._header(c, "Risk and Return by Period: Strategy vs SPY")
        wins = [w for w in ("3M", "1Y", "3Y", "5Y", "SI") if w in analytics["windows"]]
        head = ["Metric"] + [f"{w} {s}" for w in wins for s in ("Strat.", "SPY")]
        rows = [("Return (3M total, else annualized)", None), ("Total return (cumulative)", "total_return"),
                ("Volatility (ann.)", "volatility"),
                ("Sharpe ratio", "sharpe"), ("Sortino ratio", "sortino"), ("Max drawdown", "max_drawdown"),
                ("Calmar ratio", "calmar"), ("Beta vs SPY", "beta"), ("Correlation vs SPY", "correlation"),
                ("Up capture", "up_capture"),
                ("Down capture", "down_capture"), ("% days positive", "hit_rate"),
                ("Best day", "best_day"), ("Worst day", "worst_day")]
        data = [head]
        for label, key in rows:
            row = [label]
            for w in wins:
                for s in ("Strategy", "SPY"):
                    m = analytics["windows"][w]["series"][s]
                    if key is None:
                        v = m.get("cagr", m["total_return"])
                        row.append(pct(v))
                    elif key in ("total_return", "volatility", "max_drawdown", "hit_rate", "up_capture",
                                 "down_capture", "best_day", "worst_day"):
                        row.append(pct(m.get(key)) if key in m else "n/a")
                    else:
                        row.append(num(m.get(key)) if key in m else "n/a")
            data.append(row)
        data.append(["Switches / % time in SPY"] + [
            v for w in wins for v in (f"{analytics['windows'][w]['strategy_activity']['switches']} / "
                                      f"{pct(analytics['windows'][w]['strategy_activity']['pct_time_in_spy'])}", "")])
        widths = [2.1 * inch] + [0.76 * inch] * (len(head) - 1)
        h = self._table(c, data, widths, PAGE_H - 1.35 * inch, highlight_rows=(1,), padding=2)
        # 60/40 benchmark row block, so every 60/40 figure quoted elsewhere can be checked here.
        mix = [["60/40 benchmark"] + [f"{w}" for w in wins]]
        for label, key, fmt in (("Return (3M total, else ann.)", None, pct), ("Total return (cumulative)", "total_return", pct),
                                ("Volatility (ann.)", "volatility", pct),
                                ("Sharpe ratio", "sharpe", num), ("Max drawdown", "max_drawdown", pct),
                                ("Calmar ratio", "calmar", num)):
            row = [label]
            for w in wins:
                m = analytics["windows"][w]["series"]["60/40"]
                row.append(fmt(m.get("cagr", m["total_return"])) if key is None else
                           (fmt(m[key]) if key in m else "n/a"))
            mix.append(row)
        h2 = self._table(c, mix, [2.1 * inch] + [1.0 * inch] * len(wins), PAGE_H - 1.5 * inch - h, padding=2)
        ranges = ", ".join(f"{w}: {analytics['windows'][w]['start']} to {analytics['windows'][w]['end']}" for w in wins)
        note_top = PAGE_H - 1.6 * inch - h - h2          # just below the 60/40 table
        Frame(0.6 * inch, 0.66 * inch, PAGE_W - 1.2 * inch, note_top - 0.66 * inch, showBoundary=0
              ).addFromList([_p("Periods end on the last completed session. " + ranges + ". SI = since the "
                                "walk-forward start. Ratios use the 13-week T-bill as the risk-free rate. Current "
                                f"allocation: {pct(analytics['windows']['SI']['strategy_activity']['current_allocation_spy'])} SPY.",
                                "small")], c)

    def _draw_supporting(self, c, analytics):
        self._header(c, "Supporting Data: Calendar Years, Rolling Returns, Growth of $10,000")
        years = analytics.get("calendar_years", {})
        end = analytics["windows"]["SI"]["end"]
        rows = [["Year", "Strategy", "SPY", "60/40"]]
        for y, r in years.items():
            label = f"{y} YTD" if str(y) == end[:4] and end[5:] < "12-24" else str(y)
            rows.append([label, pct(r["Strategy"]), pct(r["SPY"]), pct(r["60/40"])])
        t = Table(rows, colWidths=[0.95 * inch, 0.95 * inch, 0.95 * inch, 0.95 * inch])
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 8.2), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.2),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6)]))
        w, h = t.wrapOn(c, PAGE_W, PAGE_H)
        t.drawOn(c, 0.6 * inch, PAGE_H - 1.3 * inch - h)

        roll, growth = analytics.get("rolling_1y", {}), analytics.get("growth_of_10000", {})
        side = [["Rolling 1-year returns", "Strategy", "SPY"],
                ["Best 1-year period", pct(roll.get("best_1y_strategy")), pct(roll.get("best_1y_spy"))],
                ["Worst 1-year period", pct(roll.get("worst_1y_strategy")), pct(roll.get("worst_1y_spy"))],
                ["Periods beating SPY", pct(roll.get("pct_periods_beating_spy")), ""],
                ["Median excess vs SPY", pct(roll.get("median_1y_excess")), ""],
                ["Growth of $10,000 (since walk-forward start)", "", ""]] + \
               [[f"   {k}", f"${v:,.0f}", ""] for k, v in growth.items()]
        t2 = Table(side, colWidths=[3.0 * inch, 1.0 * inch, 1.0 * inch])
        t2.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9.5),
            ("FONT", (0, 5), (0, 5), "Helvetica-Bold", 9.5),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9d9d9")),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
        _, h2 = t2.wrapOn(c, PAGE_W, PAGE_H)
        t2.drawOn(c, PAGE_W - 0.6 * inch - 5.0 * inch, PAGE_H - 1.3 * inch - h2)
        Frame(PAGE_W - 5.6 * inch, 0.75 * inch, 5.0 * inch, PAGE_H - 2.2 * inch - h2, showBoundary=0).addFromList(
            [_p(f"Calendar-year returns are total returns. The final year is year-to-date through {end}. "
                "Rolling figures cover every 252-trading-day window since the walk-forward start. "
                "60/40 is rebalanced daily, without costs.", "small")], c)

    def _draw_candidates(self, c, candidates, history, period=None):
        self._header(c, "Context: Each Moving Average Over the Full Period (IN-SAMPLE)")
        data = [["Rule (IN-SAMPLE)", "CAGR", "Volatility", "Sharpe", "Max DD", "Switches", "% in SPY",
                 "Years chosen"]]
        chosen = {}
        for h in history:
            chosen.setdefault(f"MA{h['chosen_ma']}", []).append(h["year"])
        for name, m in candidates.items():
            yrs = chosen.get(name, [])
            data.append([f"{name[2:]}-day MA switch", pct(m["cagr"]), pct(m["volatility"]), num(m["sharpe"]),
                         pct(m["max_drawdown"]), str(m["switches"]), pct(m["pct_time_in_spy"]), str(len(yrs))])
        h = self._table(c, data, [2.0 * inch, 0.95 * inch, 1.0 * inch, 0.85 * inch, 0.95 * inch, 0.9 * inch,
                                  0.95 * inch, 1.2 * inch], PAGE_H - 1.4 * inch)
        period = period or "the walk-forward period"
        Frame(0.6 * inch, 0.75 * inch, PAGE_W - 1.2 * inch, PAGE_H - 1.7 * inch - h - 0.8 * inch, showBoundary=0
              ).addFromList([_p(f"<b>IN-SAMPLE ({_safe(period)}):</b> these rows use hindsight. Picking the best "
                                "row after the fact would overstate results. The strategy instead picks a moving "
                                "average each January using only earlier data, and that walk-forward result is "
                                "what the performance pages show. \"Years chosen\" counts how many years the "
                                "walk-forward selected each rule.", "body")], c)

    def _draw_team(self, c, members, heading):
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
            Frame(x + pad, bottom + pad, col_w - 2 * pad, top - bottom - 2 * pad, showBoundary=0).addFromList(
                [KeepInFrame(col_w - 2 * pad, top - bottom - 2 * pad, flow, mode="shrink")], c)

    def _disclosures(self, c):
        self._header(c, "Important Disclosures")
        w = PAGE_W - 1.2 * inch
        Frame(0.6 * inch, 0.75 * inch, w, PAGE_H - 2.0 * inch, showBoundary=0).addFromList(
            [KeepInFrame(w, PAGE_H - 2.0 * inch,
                         [_p(d.format(cost=f"{self.cost_bps:g}"), "body") for d in DISCLOSURES], mode="shrink")], c)


def chart_path(run_dir, kind):
    return confine(Path(run_dir) / "charts" / f"{kind}.png")
