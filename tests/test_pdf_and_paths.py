import re
from pathlib import Path

import pytest
from pypdf import PdfReader

from fixtures import VALID_TEAM
from strategy import charts
from strategy.analytics import calendar_year_returns, compute_window, growth_of, rolling_summary
from strategy.backtest import candidate_table, daily_rf
from strategy.config import WINDOWS
from strategy.paths import PROJECT_DIR, ConfinementError, confine
from strategy.pdf import PERF_FOOTER, Deck
from strategy.team import FICTIONAL_LABEL, validate_team


def test_confine_rejects_outside_paths():
    for p in (PROJECT_DIR.parent / "x.txt", PROJECT_DIR / ".." / "x.txt", Path("/x.txt")):
        with pytest.raises(ConfinementError):
            confine(p)
    assert confine("runs/abc") == PROJECT_DIR / "runs" / "abc"


def test_confine_accepts_windows_extended_prefix():
    from strategy.paths import _strip_extended_prefix
    inside = PROJECT_DIR / "runs" / "x.png"
    assert _strip_extended_prefix(Path("\\\\?\\" + str(inside))) == inside
    assert _strip_extended_prefix(inside) == inside


def test_no_os_import_anywhere():
    """CLAUDE.md guardrail: no `import os` in project Python files."""
    offenders = []
    for folder in ("strategy", "evals", "tests"):
        for f in (PROJECT_DIR / folder).rglob("*.py"):
            if re.search(r"^\s*(import os\b|from os\b)", f.read_text(encoding="utf-8"), re.MULTILINE):
                offenders.append(str(f))
    assert offenders == []


def test_matplotlib_cache_confined():
    charts.assert_cache_confined()


def test_deck_has_disclosures_and_labels(workdir, prices, backtest_result):
    wf, returns = backtest_result
    analytics = {"windows": {w: compute_window(returns, w) for w in WINDOWS},
                 "rolling_1y": rolling_summary(returns), "growth_of_10000": growth_of(returns),
                 "calendar_years": calendar_year_returns(returns)}
    eq = charts.render("equity_vs_spy", workdir / "charts", returns)
    team, _ = validate_team(VALID_TEAM)
    deck = Deck("Test Deck", "Subtitle")
    deck.add_slide("Performance", ["Strong risk-adjusted results."], eq, performance=True)
    deck.add_slide("How it works", ["Holds SPY or IEF."], None, performance=False)
    deck.add_metrics_table(analytics)
    deck.add_candidates_table(candidate_table(prices, wf, daily_rf(prices)), wf["selection_history"])
    deck.add_team(team)
    pdf = deck.build(workdir / "deck.pdf")

    pages = [p.extract_text() for p in PdfReader(str(pdf)).pages]
    norm = [re.sub(r"\s+", " ", t) for t in pages]
    footer_start = PERF_FOOTER[:40]
    assert footer_start in norm[1]                 # performance slide
    assert footer_start not in norm[2]             # non-performance slide
    assert footer_start in norm[3] and footer_start in norm[4]   # metrics + in-sample tables
    assert "IN-SAMPLE" in norm[4]
    # Regression: the metrics-table footnote was silently dropped when its frame had no room.
    assert "Periods end on the last completed session" in norm[3] and "Current allocation" in norm[3]
    assert sum(t.count(FICTIONAL_LABEL) for t in norm) >= 6
    assert "Important Disclosures" in norm[-1]
    assert len(pages) == 1 + 4 + 2 + 1             # cover, 4 pages, 2 team pages, disclosures


def test_performance_footer_is_true_for_both_strategies():
    """Regression: the footer said 'net of modeled trading costs' on momentum pages, which are gross."""
    assert "momentum results exclude trading costs" in PERF_FOOTER
    assert "MA strategy results are net of modeled trading costs" in PERF_FOOTER


def test_long_titles_are_never_dropped(workdir):
    """Regression: a two-line title didn't fit the header frame and ReportLab silently omitted it."""
    long_title = "A Deliberately Long Slide Title That Will Certainly Wrap Onto A Second Line Of Text Here"
    deck = Deck("T", "S")
    deck.add_slide(long_title, ["One bullet."])
    pages = [re.sub(r"\s+", " ", p.extract_text()) for p in PdfReader(str(deck.build(workdir / "t.pdf"))).pages]
    assert "Deliberately Long Slide Title" in pages[1]


def test_every_code_page_has_its_title(workdir, prices, backtest_result):
    """Every code-generated page must render its header (traceability evals locate pages by these titles)."""
    from strategy.analytics import comparison_extras, comparison_window
    from strategy.config import COMPARISON_WINDOWS, MomentumConfig
    from strategy.momentum import add_to_returns, run_all_momentum
    from strategy.pdf import CODE_PAGE_TITLES
    wf, returns = backtest_result
    mom = run_all_momentum(prices, MomentumConfig())
    returns = add_to_returns(returns, mom)
    comp = {"windows": {w: comparison_window(returns, w, (3, 6, 12, 24)) for w in COMPARISON_WINDOWS},
            **comparison_extras(returns, (3, 6, 12, 24))}
    analytics = {"windows": {w: compute_window(returns, w) for w in WINDOWS}, "rolling_1y": rolling_summary(returns),
                 "growth_of_10000": growth_of(returns), "calendar_years": calendar_year_returns(returns)}
    deck = Deck("T", "S")
    deck.add_metrics_table(analytics)
    deck.add_candidates_table(candidate_table(prices, wf, daily_rf(prices)), wf["selection_history"])
    deck.add_comparison_table(comp)
    deck.add_momentum_supporting(comp, {f"MOM{L}": r["summary"] for L, r in mom.items()})
    deck.add_supporting_data(analytics)
    text = " ".join(re.sub(r"\s+", " ", p.extract_text()) for p in PdfReader(str(deck.build(workdir / "c.pdf"))).pages)
    assert [t for t in CODE_PAGE_TITLES if t not in text] == []


def test_all_charts_render(workdir, prices, backtest_result):
    from strategy.analytics import comparison_window
    from strategy.config import COMPARISON_WINDOWS, MomentumConfig
    from strategy.momentum import add_to_returns, run_all_momentum
    wf, returns = backtest_result
    returns = add_to_returns(returns, run_all_momentum(prices, MomentumConfig()))
    analytics = {"windows": {w: compute_window(returns, w) for w in WINDOWS},
                 "comparison": {"windows": {w: comparison_window(returns, w, (3, 6, 12, 24)) for w in COMPARISON_WINDOWS}}}
    for kind in charts.CHART_KINDS:
        path = charts.render(kind, workdir / "charts", returns, analytics=analytics, history=wf["selection_history"])
        assert path.exists() and path.stat().st_size > 10_000
