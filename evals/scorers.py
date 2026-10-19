"""Scorers: each takes a run directory and returns a Score.

Every scorer is code-graded and deterministic, so evals are cheap to re-run on
saved runs. Live evals generate fresh runs, then score them with the same code.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from strategy.analytics import compute_window
from strategy.backtest import run_all
from strategy.config import PipelineConfig, StrategyConfig, WINDOWS
from strategy.guardrails import (NumberIndex, banned_phrases, extract_numbers, persona_mentions,
                                 unsupported_numbers)
from strategy.paths import confine, read_json
from strategy.pdf import DISCLOSURES, GEN_FOOTER, PERF_FOOTER
from strategy.team import FICTIONAL_LABEL, validate_team

CURRENT_YEAR = pd.Timestamp.today().year


@dataclass
class Score:
    name: str
    score: float                # 0..1
    threshold: float
    details: dict = field(default_factory=dict)

    @property
    def passed(self):
        return self.score >= self.threshold

    def to_dict(self):
        return {**asdict(self), "passed": self.passed}


class Run:
    """Lazy access to a run directory's artifacts."""

    def __init__(self, path):
        self.dir = confine(path)

    def json(self, name):
        p = self.dir / name
        return read_json(p) if p.exists() else None

    def csv(self, name):
        p = self.dir / name
        return pd.read_csv(p, index_col=0, parse_dates=True) if p.exists() else None

    def trace(self):
        p = self.dir / "trace.jsonl"
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l] if p.exists() else []

    def pdf_pages(self):
        from pypdf import PdfReader
        p = self.dir / "presentation.pdf"
        if not p.exists():
            return []
        return [re.sub(r"\s+", " ", page.extract_text() or "") for page in PdfReader(str(p)).pages]

    def number_index(self):
        dr = self.json("data_report.json") or {}
        return NumberIndex(self.json("analytics.json") or {}, self.json("backtest.json") or {},
                           {"rows": dr.get("rows")}, constants=StrategyConfig().constants())


def _missing(name, threshold, what):
    return Score(name, 0.0, threshold, {"error": f"missing {what}"})


# ---------------------------------------------------------------- data/backtest

def data_integrity(run, threshold=1.0):
    prices = run.csv("prices.csv")
    if prices is None:
        return _missing("data_integrity", threshold, "prices.csv")
    checks = {
        "has_all_tickers": {"SPY", "IEF", "^IRX"} <= set(prices.columns),
        "no_missing_etf_prices": bool(prices[["SPY", "IEF"]].notna().all().all()),
        "at_least_15_years": (prices.index.max() - prices.index.min()).days > 15 * 365,
        "recent_data": (pd.Timestamp.today() - prices.index.max()).days < 10,
        "monotonic_dates": bool(prices.index.is_monotonic_increasing),
        "positive_prices": bool((prices[["SPY", "IEF"]] > 0).all().all()),
    }
    return Score("data_integrity", sum(checks.values()) / len(checks), threshold, checks)


def backtest_tool_coverage(run, threshold=1.0):
    calls = [e for e in run.trace() if e.get("type") == "tool" and e.get("agent") == "Backtest Agent" and e.get("ok")]
    mas = {c["input"].get("ma_days") for c in calls if c["tool"] == "run_ma_backtest"}
    checks = {f"ran_MA{n}": n in mas for n in StrategyConfig().ma_windows}
    checks["ran_walk_forward"] = any(c["tool"] == "run_walk_forward" for c in calls)
    checks["compared_candidates"] = any(c["tool"] == "compare_candidates" for c in calls)
    return Score("backtest_tool_coverage", sum(checks.values()) / len(checks), threshold, checks)


def backtest_reproducible(run, threshold=1.0):
    prices, saved = run.csv("prices.csv"), run.csv("returns.csv")
    if prices is None or saved is None:
        return _missing("backtest_reproducible", threshold, "prices.csv/returns.csv")
    _, fresh = run_all(prices, StrategyConfig())
    cols = ["Strategy", "SPY", "60/40", "w_spy"]
    diff = float((fresh[cols] - saved[cols]).abs().max().max())
    return Score("backtest_reproducible", 1.0 if diff < 1e-10 else 0.0, threshold, {"max_abs_diff": diff})


def analytics_consistency(run, threshold=1.0):
    returns, saved = run.csv("returns.csv"), run.json("analytics.json")
    if returns is None or saved is None:
        return _missing("analytics_consistency", threshold, "returns.csv/analytics.json")
    bad = []
    for w in WINDOWS:
        fresh = compute_window(returns, w)
        for s, metrics in fresh["series"].items():
            for k, v in metrics.items():
                old = saved["windows"].get(w, {}).get("series", {}).get(s, {}).get(k)
                if old is None or (v == v and abs(v - old) > 1e-9):
                    bad.append(f"{w}/{s}/{k}")
    checks = len(WINDOWS) * 3
    return Score("analytics_consistency", 1.0 if not bad else 0.0, threshold,
                 {"windows_checked": checks, "mismatches": bad[:20]})


# ------------------------------------------------------------- narrative/compliance

def agent_texts(run):
    """Every agent-written string that reaches the PDF, with its source."""
    texts = []
    for s in run.json("slides.json") or []:
        if s.get("type") == "slide":
            texts.append(("slide: " + s["title"], " \n".join([s["title"], *s["bullets"]])))
    for i, f in enumerate((run.json("analytics.json") or {}).get("findings", [])):
        texts.append((f"finding {i + 1}", f))
    return texts


def narrative_faithfulness(run, threshold=1.0):
    index = run.number_index()
    total, unsupported = 0, []
    for src, text in agent_texts(run):
        nums = list(extract_numbers(text))
        total += len(nums)
        for raw in unsupported_numbers(text, index):
            unsupported.append(f"{src}: {raw}")
    if total == 0:
        return Score("narrative_faithfulness", 0.0, threshold, {"error": "no numbers found in narrative"})
    return Score("narrative_faithfulness", 1 - len(unsupported) / total, threshold,
                 {"numbers_checked": total, "unsupported": unsupported})


def compliance_language(run, threshold=1.0):
    """Banned phrases anywhere agent-written, and fictional personas named outside the labeled team pages."""
    hits = []
    team = run.json("team.json") or {}
    for src, text in agent_texts(run):
        hits += [f"{src}: {p}" for p in banned_phrases(text)]
        if src.startswith("slide"):
            hits += [f"{src}: names persona {n} outside the labeled team pages" for n in persona_mentions(text, team)]
    for m in team.get("members", []):
        hits += [f"bio {m['name']}: {p}" for p in banned_phrases(m["bio"])]
    n = len(agent_texts(run)) + len(team.get("members", []))
    return Score("compliance_language", 1.0 if not hits else 0.0, threshold, {"texts_checked": n, "violations": hits})


def pdf_disclosures(run, threshold=1.0):
    pages = run.pdf_pages()
    if not pages:
        return _missing("pdf_disclosures", threshold, "presentation.pdf")
    slides = run.json("slides.json") or []
    perf_key, gen_key = PERF_FOOTER[:45], GEN_FOOTER[:30]
    # Page 1 is the cover. Each slide/standard page then maps to one page, except team, which spans two.
    expected = []
    for s in slides:
        perf = s.get("performance", s["type"] in ("metrics_table", "in_sample_comparison"))
        expected += [perf] * (2 if s["type"] == "team" else 1)
    body = pages[1:1 + len(expected)]
    missing = [i + 2 for i, (want, text) in enumerate(zip(expected, body)) if want and perf_key not in text]
    unfootered = [i + 2 for i, text in enumerate(body) if perf_key not in text and gen_key not in text]
    checks = {
        "every_performance_page_has_disclosure": not missing,
        "every_page_has_a_footer": not unfootered,
        "disclosures_page_last": "Important Disclosures" in pages[-1] and "Hypothetical performance" in pages[-1],
        "in_sample_labeled": any("IN-SAMPLE" in p for p in pages),
        "cover_marks_hypothetical": "Hypothetical backtested" in pages[0],
        "cost_assumption_stated": bool(re.search(r"\d+(\.\d+)? basis points per full switch", pages[-1])),
        "partial_year_labeled_ytd": _partial_year_ok(run, pages),
    }
    return Score("pdf_disclosures", sum(checks.values()) / len(checks), threshold,
                 {**checks, "pages_missing_disclosure": missing})


def _partial_year_ok(run, pages):
    """If the deck shows calendar-year results and the last year is incomplete, it must say YTD."""
    returns = run.csv("returns.csv")
    if returns is None:
        return False
    end = returns.index.max()
    partial = (end.month, end.day) < (12, 24)
    shows_years = any("calendar" in p.lower() for p in pages)
    return not (partial and shows_years) or any("YTD" in p or "year-to-date" in p.lower() for p in pages)


def balance_and_traceability(run, threshold=1.0):
    """The pitch acknowledges every window where the strategy did worse than SPY, and every
    agent-cited figure appears in a code-generated table of the PDF."""
    from strategy.agents.presentation_agent import unacknowledged_adverse
    analytics, slides = run.json("analytics.json"), run.json("slides.json") or []
    pages = run.pdf_pages()
    if not analytics or not pages:
        return _missing("balance_and_traceability", threshold, "analytics.json/presentation.pdf")
    unack = unacknowledged_adverse(analytics, slides)
    # Traceability: numbers on agent slides must appear verbatim on a code-generated page
    # (metrics table, in-sample table, supporting data). Those are the pages without agent prose.
    agent_titles = {s["title"] for s in slides if s["type"] == "slide"}
    table_text = " ".join(p for p in pages[1:-1] if not any(t[:30] in p for t in agent_titles))
    untraced = []
    for s in slides:
        if s["type"] != "slide":
            continue
        for value, decimals, raw, unit in extract_numbers(" ".join(s["bullets"])):
            if unit == "%" and decimals == 1 and raw.lstrip("-−+") not in table_text:
                untraced.append(f"{s['title']}: {raw}")
    checks = {"adverse_windows_acknowledged": not unack, "cited_percentages_traceable": not untraced}
    return Score("balance_and_traceability", sum(checks.values()) / len(checks), threshold,
                 {**checks, "unacknowledged": unack, "untraced": untraced[:15]})


def team_quality(run, threshold=1.0):
    team = run.json("team.json")
    if not team:
        return _missing("team_quality", threshold, "team.json")
    _, err = validate_team(team["members"])
    members = team["members"]
    pm = [m for m in members if m["role"] == "Portfolio Manager"]
    plausible = []
    for m in members:
        first_grad = min(e["year"] for e in m["education"])
        plausible.append(m["years_experience"] <= CURRENT_YEAR - first_grad + 2)
    pages = run.pdf_pages()
    checks = {
        "schema_valid": err is None,
        "one_pm_five_analysts": len(pm) == 1 and len(members) == 6,
        "pm_most_senior": bool(pm) and pm[0]["years_experience"] >= max(m["years_experience"] for m in members),
        "careers_plausible": all(plausible),
        "certified_members": sum(bool(m["certifications"]) for m in members) >= 3,
        "fictional_label_on_every_card": sum(p.count(FICTIONAL_LABEL) for p in pages) >= 6,
        "team_pages_in_pdf": sum("Digital Investment Team" in p for p in pages) == 2,
    }
    return Score("team_quality", sum(checks.values()) / len(checks), threshold, {**checks, "validation_error": err})


def pdf_structure(run, threshold=1.0):
    p = run.dir / "presentation.pdf"
    if not p.exists():
        return _missing("pdf_structure", threshold, "presentation.pdf")
    import pymupdf
    doc = pymupdf.open(str(p))
    images = sum(len(page.get_images()) for page in doc)
    pages = run.pdf_pages()
    text = " ".join(pages).lower()
    slides = run.json("slides.json") or []
    checks = {
        "page_count_10_to_20": 10 <= len(pages) <= 20,
        "at_least_3_charts": images >= 3,
        "has_metrics_table": "risk and return by period" in text,
        "mentions_spy_comparison": text.count("spy") >= 10,
        "covers_all_periods": all(w.lower() in text for w in ("3M", "1Y", "3Y", "5Y")),
        "discusses_tradeoffs": any(k in text for k in ("lag", "underperform", "trade-off", "tradeoff")),
        "agent_slides_6_to_12": 6 <= sum(s["type"] == "slide" for s in slides) <= 12,
    }
    return Score("pdf_structure", sum(checks.values()) / len(checks), threshold,
                 {**checks, "pages": len(pages), "images": images})


def run_health(run, threshold=1.0, max_cost_usd=15.0):
    m = run.json("manifest.json") or {}
    trace = run.trace()
    tools = [e for e in trace if e.get("type") == "tool"]
    errors = [e for e in tools if not e.get("ok")]
    agents = {e["agent"] for e in trace if e.get("type") == "finish"}
    checks = {
        "status_ok": m.get("status") == "ok",
        "all_five_agents_finished": {"Data Agent", "Backtest Agent", "Analytics Agent", "Team Agent",
                                     "Presentation Agent"} <= agents,
        "no_tool_crashes": not any(e.get("type") == "tool_crash" for e in trace),
        "cost_under_cap": (m.get("cost_usd") or 0) <= max_cost_usd,
    }
    return Score("run_health", sum(checks.values()) / len(checks), threshold,
                 {**checks, "cost_usd": m.get("cost_usd"), "seconds": m.get("seconds"),
                  "tool_calls": len(tools), "tool_errors_self_corrected": len(errors)})


SCORERS = [run_health, data_integrity, backtest_tool_coverage, backtest_reproducible, analytics_consistency,
           narrative_faithfulness, compliance_language, pdf_disclosures, balance_and_traceability, team_quality,
           pdf_structure]


def score_run(path):
    run = Run(path)
    return [scorer(run) for scorer in SCORERS]


def render_pages(run_dir, zoom=1.4):
    """Render each PDF page to PNG under <run>/pages/ for visual review."""
    import pymupdf
    run_dir = confine(run_dir)
    out = confine(Path(run_dir) / "pages")
    out.mkdir(exist_ok=True)
    paths = []
    for i, page in enumerate(pymupdf.open(str(run_dir / "presentation.pdf")), start=1):
        target = confine(out / f"page-{i:02d}.png")
        page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(str(target))
        paths.append(target)
    return paths
