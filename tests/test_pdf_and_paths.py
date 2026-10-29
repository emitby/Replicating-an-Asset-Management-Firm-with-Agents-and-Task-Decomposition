"""PDF structure, rebuild-from-artifacts, governance consistency, and filesystem guardrails."""

import json
import re
import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader

from strategy import charts, governance
from strategy.hooks import HOOK_DESCRIPTIONS, default_hooks
from strategy.paths import PROJECT_DIR, ConfinementError, confine
from strategy.pdf import TABLE_PAGE_PREFIX, TITLE, build_from_run, pct
from strategy.team import FICTIONAL_LABEL


def pages(path):
    return [re.sub(r"\s+", " ", p.extract_text() or "") for p in PdfReader(str(path)).pages]


# ------------------------------------------------------------------ the deck

def test_deck_structure(offline_run):
    text = pages(offline_run.path("presentation.pdf"))
    assert PdfReader(str(offline_run.path("presentation.pdf"))).metadata.title == TITLE
    assert TITLE in text[0] and "How AI agents produced this presentation" in text[0] and "back-and-forth" in text[0]
    assert "The Agentic Workflow" in text[1]
    assert "The Harness" in text[2] and "Guardrails and Evals" in text[3]
    tables = [p for p in text if p.lstrip().startswith(TABLE_PAGE_PREFIX)]
    assert len(tables) == 2                                                          # user requirement
    assert "Correlation with SPY" in tables[0] and "Corr. SPY" in tables[1]       # user requirement
    assert sum("simulated conversation" in p for p in text) == 1
    meeting = next(i for i, p in enumerate(text) if "simulated conversation" in p)
    assert text[meeting + 1].lstrip().startswith("Constructive Feedback")             # user request
    assert text[meeting + 2].lstrip().startswith("Harsh Feedback")                    # user request
    assert sum("Decision Log, Round 1" in p for p in text) == 2 and sum("Decision Log, Round 2" in p for p in text) == 1
    assert sum(p.count(FICTIONAL_LABEL) for p in text) >= 6
    assert "Important Disclosures" in text[-1] and "exclude trading costs" in text[-1]


def test_harness_page_shows_this_runs_cost(offline_run):
    """The harness re-renders the PDF after writing the manifest, so the cost table is filled in."""
    harness_page = pages(offline_run.path("presentation.pdf"))[2]
    m = json.loads(offline_run.path("manifest.json").read_text(encoding="utf-8"))
    assert f"${m['cost_usd']:.2f}" in harness_page and "Research Agent" in harness_page


def test_pdf_rebuilds_from_saved_artifacts_after_editing(offline_run, workdir):
    """User requirement: the PDF can be edited and rebuilt without re-running any agent."""
    copy = workdir / "copy"
    shutil.copytree(offline_run.run_dir, copy)
    deck = json.loads((copy / "deck.json").read_text(encoding="utf-8"))
    deck["slides"][0]["title"] = "Edited Executive Summary"
    (copy / "deck.json").write_text(json.dumps(deck), encoding="utf-8")
    out = build_from_run(copy, "edited.pdf")
    assert any("Edited Executive Summary" in p for p in pages(out))


def test_pitchbook(offline_run):
    """User request: a short "Pitchbook" with summary, performance, team (0 years), investment process, feedback,
    compliance (fictional standards labelled) and disclosures, plus an appendix holding every other page."""
    from evals.scorers import Run, pitchbook_structure
    score = pitchbook_structure(Run(offline_run.run_dir))
    assert score.passed, score.details
    text = pages(offline_run.path("pitchbook.pdf"))
    contents = next(i for i, p in enumerate(text) if p.lstrip().startswith("Appendix Section"))
    assert contents <= 11                                       # the main section is short
    assert all("APPENDIX" in p for p in text[contents + 1:])    # every appendix page carries its section tag
    assert "does not claim compliance with the Global Investment Performance Standards" in " ".join(text)


def test_pitchbook_rebuilds_from_saved_artifacts(offline_run, workdir):
    from strategy.pitchbook import build_pitchbook_from_run
    copy = workdir / "copy"
    shutil.copytree(offline_run.run_dir, copy)
    out = build_pitchbook_from_run(copy, "rebuilt.pdf")
    assert len(PdfReader(str(out)).pages) == len(PdfReader(str(offline_run.path("pitchbook.pdf"))).pages)


def test_build_from_run_names_missing_artifacts(workdir):
    with pytest.raises(FileNotFoundError, match="deck.json"):
        build_from_run(workdir)


@pytest.mark.parametrize("text, phrase", [
    ("Its correlation with SPY of 0.16 is low.", "correlation with SPY of 0.16"),
    ("The variants show 0.13 to 0.16 correlation to SPY since inception.", "0.13 to 0.16 correlation to SPY"),
    ("Final five correlations of 0.13-0.36 vs QQQ's 0.93.", "correlations of 0.13-0.36"),
    ("Correlation with SPY: 0.16 (QQQ: 0.93).", "Correlation with SPY: 0.16"),
])
def test_correlation_phrases_are_highlighted(text, phrase):
    """User requirement: correlation is highlighted wherever the commentary explains benefits."""
    from strategy.pdf import _highlight
    assert f'<b><font color="#1f4e79">{phrase}</font></b>' in _highlight(text)


def test_other_ratios_are_not_highlighted():
    from strategy.pdf import _highlight
    text = "Sharpe of 0.84 vs SPY's 0.76; total return 834.9%."
    assert _highlight(text) == text


def test_no_negative_zero_in_formatting():
    assert pct(-0.00001) == "0.0%" and pct(0.1234) == "12.3%" and pct(None) == "n/a"


def test_all_charts_render(offline_run, workdir):
    from strategy.pdf import load_run
    data = load_run(offline_run.run_dir).chart_data()
    for kind in charts.CHART_KINDS:
        path = charts.render(kind, workdir / "charts", data)
        assert path.exists() and path.stat().st_size > 10_000


# ------------------------------------------------------------------ governance text matches the code

def test_governance_evals_match_the_scorers():
    from evals.scorers import SCORERS
    assert [s.__name__ for s in SCORERS] == list(governance.EVALS)


def test_every_installed_hook_is_described():
    hooks = default_hooks()
    described = " ".join(HOOK_DESCRIPTIONS)
    for h in [*hooks.pre, *hooks.post]:
        assert getattr(h, "__name__") in described


# ------------------------------------------------------------------ filesystem guardrails

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
    for folder in ("strategy", "evals", "tests", ".claude"):
        for f in (PROJECT_DIR / folder).rglob("*.py"):
            if re.search(r"^\s*(import os\b|from os\b)", f.read_text(encoding="utf-8"), re.MULTILINE):
                offenders.append(str(f))
    assert offenders == []


def test_matplotlib_cache_confined():
    charts.assert_cache_confined()


def test_latest_run_is_none_on_a_fresh_clone(monkeypatch):
    """Regression (found by the Evals CI workflow): with no runs/ folder yet, ``eval`` crashed in
    ``latest_run`` instead of reporting "No runs found". It now returns None."""
    import strategy.cli as cli
    from strategy.paths import CACHE_DIR
    monkeypatch.setattr(cli, "RUNS_DIR", CACHE_DIR / "test-output" / "no-runs-here")
    assert cli.latest_run() is None
