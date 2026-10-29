"""Scorers: each takes a run directory and returns a Score.

Every scorer is code-graded and deterministic, so evals are cheap to re-run on
saved runs. Live evals generate fresh runs, then score them with the same code.
The scorer names match `strategy.governance.EVALS` one-to-one (a unit test
checks this), so the PDF's evals page always describes what actually runs.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from evals.crosscheck_ranking import crosscheck
from strategy.config import UNIVERSE, RankingConfig
from strategy.guardrails import NumberIndex, banned_phrases, persona_mentions, unsupported_numbers
from strategy.hooks import default_hooks
from strategy.paths import confine, read_json
from strategy.pdf import SECTIONS, TABLE_PAGE_PREFIX, TITLE
from strategy.ranking import (RankingError, StrategySpec, apply_replacement, daily_rf, grid, run_strategy, score,
                              top_n, validate_proposal)
from strategy.team import FICTIONAL_LABEL, validate_team

CURRENT_YEAR = pd.Timestamp.today().year
AGENT_NAMES = ("Data Agent", "Research Agent", "Portfolio Manager Agent", "Analytics Agent", "Team Agent",
               "Presentation Agent")


@dataclass
class Score:
    """One scorer's result: a 0..1 score, its pass threshold, and the individual checks."""
    name: str
    score: float
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
        """A JSON artifact, or None if missing."""
        p = self.dir / name
        return read_json(p) if p.exists() else None

    def csv(self, name):
        """A CSV artifact indexed by date, or None if missing."""
        p = self.dir / name
        return pd.read_csv(p, index_col=0, parse_dates=True) if p.exists() else None

    def trace(self):
        """The trace events (list of dicts)."""
        p = self.dir / "trace.jsonl"
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line] if p.exists() else []

    def pdf_pages(self):
        """Text of each PDF page, whitespace-normalized."""
        from pypdf import PdfReader
        p = self.dir / "presentation.pdf"
        if not p.exists():
            return []
        return [re.sub(r"\s+", " ", page.extract_text() or "") for page in PdfReader(str(p)).pages]

    def scores(self):
        """The scores table from research.json (rows: ids, SPY, QQQ)."""
        return pd.DataFrame(self.json("research.json")["scores"]).T

    def number_index(self):
        """The same citable-number index the pipeline used (`RunContext.number_index`), rebuilt from artifacts."""
        research, pm = self.json("research.json") or {}, self.json("pm.json") or {}
        dr = self.json("data_report.json") or {}
        params = {v for p in pm.get("proposals", []) for v in (p["sma"], p["lookback_days"])}
        return NumberIndex(research.get("scores", {}), research.get("facts", {}), self.json("analytics.json") or {},
                           (pm.get("final") or {}).get("replacements", []), {"rows": dr.get("cleaned_rows")},
                           constants=RankingConfig().constants() | params)


def _missing(name, threshold, what):
    return Score(name, 0.0, threshold, {"error": f"missing {what}"})


def _score(name, checks, threshold, **details):
    return Score(name, sum(map(bool, checks.values())) / len(checks), threshold, {**checks, **details})


def agent_texts(run):
    """Every agent-written string that reaches the PDF, as (where, text) pairs."""
    out = []
    deck = run.json("deck.json") or {}
    for s in deck.get("slides", []):
        out.append((f"slide {s['title']!r}", " \n".join([s["title"], *s["bullets"]])))
    for f in (run.json("analytics.json") or {}).get("findings", []):
        out.append(("analytics finding", f))
    research = run.json("research.json") or {}
    for r, data in research.get("rounds", {}).items():
        out += [(f"research r{r}", t) for t in [data["message"], *data["findings"]]]
    pm = run.json("pm.json") or {}
    for item in pm.get("top5", []) + pm.get("proposals", []) + (pm.get("final") or {}).get("decisions", []):
        out += [(f"pm {item['id']}", item[k]) for k in ("rationale", "hypothesis", "pro", "con") if k in item]
    out += [("pm message", t) for t in (pm.get("message_to_research"), (pm.get("final") or {}).get("message")) if t]
    out += [("meeting", line["text"]) for line in pm.get("meeting", [])]
    out += [(f"feedback {kind}", line["text"]) for kind, lines in pm.get("feedback", {}).items() for line in lines]
    return out


# ------------------------------------------------------------------ run and data

def run_health(run, threshold=1.0, max_cost_usd=25.0):
    m = run.json("manifest.json")
    if not m:
        return _missing("run_health", threshold, "manifest.json")
    events = run.trace()
    finished = {e["agent"] for e in events if e.get("type") == "finish"}
    checks = {"status_ok": m["status"] == "ok",
              **{f"{a} finished": a in finished for a in AGENT_NAMES},
              "no_tool_crash": not any(e.get("type") == "tool_crash" for e in events),
              "cost_under_cap": m["cost_usd"] <= max_cost_usd}
    return _score("run_health", checks, threshold, cost_usd=m["cost_usd"])


def data_integrity(run, threshold=1.0):
    prices = run.csv("prices.csv")
    if prices is None:
        return _missing("data_integrity", threshold, "prices.csv")
    cols = [*UNIVERSE, "^IRX"]
    checks = {
        "all_tickers": set(cols) <= set(prices.columns),
        "no_missing_etf_prices": prices.reindex(columns=list(UNIVERSE)).notna().all().all(),
        "positive_prices": (prices.reindex(columns=list(UNIVERSE)) > 0).all().all(),
        "ten_years": (prices.index.max() - prices.index.min()).days >= 10 * 365,
        "recent": (pd.Timestamp.today() - prices.index.max()).days <= 10,
        "sorted_unique_dates": prices.index.is_monotonic_increasing and prices.index.is_unique,
        "completed_sessions_only": prices.index.max().normalize() < pd.Timestamp.today().normalize(),
    }
    return _score("data_integrity", checks, threshold)


# ------------------------------------------------------------------ research

def research_coverage(run, threshold=1.0):
    research, pm = run.json("research.json"), run.json("pm.json")
    if not research or not pm:
        return _missing("research_coverage", threshold, "research.json or pm.json")
    grid_ids = [s.id for s in grid(RankingConfig())]
    rounds = research["rounds"]
    calls = [e for e in run.trace() if e.get("type") == "tool" and e.get("ok")]
    ran = {StrategySpec(e["input"]["portfolio"], e["input"]["sma"], e["input"]["lookback_days"]).id
           for e in calls if e["tool"] == "run_strategy"}
    proposals = {p["id"] for p in pm.get("proposals", [])}
    checks = {
        "round1_is_full_grid": rounds.get("1", {}).get("ids") == grid_ids,
        "run_grid_called": any(e["tool"] == "run_grid" for e in calls),
        "round2_is_proposals": set(rounds.get("2", {}).get("ids", [])) == proposals,
        "every_proposal_run": proposals <= ran,
        "every_strategy_scored": set(grid_ids) | proposals <= set(research["scores"]),
    }
    return _score("research_coverage", checks, threshold)


def research_reproducible(run, threshold=1.0, tol=1e-10):
    prices, returns, research = run.csv("prices.csv"), run.csv("strategy_returns.csv"), run.json("research.json")
    if prices is None or returns is None or not research:
        return _missing("research_reproducible", threshold, "prices, returns or research")
    px = prices[list(UNIVERSE)]
    ids = [c for c in returns.columns if c not in ("SPY", "QQQ", "rf")]
    rerun = {sid: run_strategy(px, StrategySpec.from_id(sid))[0] for sid in ids}
    worst = max(float((rerun[sid].reindex(returns.index) - returns[sid]).abs().max()) for sid in ids)
    rescored = score(rerun, prices, pd.Timestamp(research["window_start"]), daily_rf(prices))
    saved = pd.DataFrame(research["scores"]).T
    cols = [c for c in rescored.columns if c in saved.columns]   # runs saved before corr_spy lack that column
    score_diff = float((rescored[cols] - saved.loc[rescored.index, cols]).abs().max().max())
    checks = {"returns_match": worst <= tol, "scores_match": score_diff <= 1e-9}
    return _score("research_reproducible", checks, threshold, max_return_diff=worst, max_score_diff=score_diff)


def notebook_crosscheck(run, threshold=1.0):
    prices, returns = run.csv("prices.csv"), run.csv("strategy_returns.csv")
    if prices is None or returns is None:
        return _missing("notebook_crosscheck", threshold, "prices.csv or strategy_returns.csv")
    result = crosscheck(prices, returns, UNIVERSE)
    checks = {"all_strategies_match_notebook": not result["mismatched"], "checked_all": result["checked"] >= 89}
    return _score("notebook_crosscheck", checks, threshold, **result)


# ------------------------------------------------------------------ PM protocol and dialogue

def pm_protocol(run, threshold=1.0):
    research, pm = run.json("research.json"), run.json("pm.json")
    if not research or not pm or "final" not in pm:
        return _missing("pm_protocol", threshold, "research.json or a finalized pm.json")
    cfg, sc = RankingConfig(), run.scores()
    r1 = research["rounds"]["1"]["ids"]
    top = [p["id"] for p in pm["top5"]]
    props = pm["proposals"]
    valid = True
    seen = set(r1)
    for p in props:
        try:
            validate_proposal(StrategySpec(p["portfolio"], p["sma"], p["lookback_days"]), cfg, seen)
        except RankingError:
            valid = False
        seen.add(p["id"])
    expected = apply_replacement(sc, top, [p["id"] for p in props])
    removed = {r["removed"] for r in expected["replacements"]}
    decided = {d["id"] for d in pm["final"]["decisions"]}
    texts_ok = all(item.get(k, "").strip() for item in pm["top5"] + props + pm["final"]["decisions"]
                   for k in ("pro", "con"))
    checks = {
        "top5_is_total_return_top5": top == top_n(sc, cfg.top_n, r1),
        "five_proposals": len(props) == cfg.n_proposals,
        "proposals_new_and_valid": valid and len({p["id"] for p in props}) == len(props),
        "final_follows_replacement_rule": pm["final"]["final"] == expected["final"],
        "decision_for_each_final_and_removed": decided == set(expected["final"]) | removed,
        "every_item_has_pro_and_con": texts_ok,
    }
    return _score("pm_protocol", checks, threshold, replacements=expected["replacements"])


def _feedback_ok(feedback):
    """Both feedback scripts exist and cover their required topics (the same rules `write_feedback` enforces)."""
    from strategy.agents.pm_agent import FEEDBACK_LINES, FEEDBACK_TOPICS, HARSH_CONS
    if set(feedback) != {"constructive", "harsh"}:
        return False
    for kind, lines in feedback.items():
        body = " ".join(line["text"] for line in lines).lower()
        if not FEEDBACK_LINES[0] <= len(lines) <= FEEDBACK_LINES[1]:
            return False
        if not all(any(w in body for w in words) for words in FEEDBACK_TOPICS[kind].values()):
            return False
        if kind == "harsh" and sum(any(w in body for w in words) for words in HARSH_CONS.values()) < 2:
            return False
    return True


def dialogue_complete(run, threshold=1.0):
    dialogue, pm, research = run.json("dialogue.json"), run.json("pm.json"), run.json("research.json")
    if dialogue is None or not pm or not research:
        return _missing("dialogue_complete", threshold, "dialogue.json, pm.json or research.json")
    pairs = [(d["from"], d["to"], d["round"]) for d in dialogue]
    meeting = pm.get("meeting", [])
    body = " ".join(line["text"] for line in meeting).lower()
    speakers = {s: sum(line["speaker"] == s for line in meeting)
                for s in ("Portfolio Manager Agent", "Research Agent", "Analytics Agent")}

    def pros_cons(r):
        f = research["rounds"].get(r, {}).get("findings", [])
        return sum(x.lower().startswith("pro:") for x in f) >= 2 and sum(x.lower().startswith("con:") for x in f) >= 2

    checks = {
        "research_to_pm_round1": ("Research Agent", "Portfolio Manager Agent", 1) in pairs,
        "pm_to_research_round1": ("Portfolio Manager Agent", "Research Agent", 1) in pairs,
        "research_to_pm_round2": ("Research Agent", "Portfolio Manager Agent", 2) in pairs,
        "pm_final_message": ("Portfolio Manager Agent", "All agents", 2) in pairs,
        "findings_have_pros_and_cons": pros_cons("1") and pros_cons("2"),
        "meeting_length": 8 <= len(meeting) <= 14,
        "meeting_all_speakers": min(speakers.values()) >= 2,
        "meeting_covers_objective_and_comparison": ("objective" in body or "goal" in body)
                                                   and any(w in body for w in ("compar", "versus", " vs ")),
        "meeting_covers_spy_and_risk": "spy" in body and ("drawdown" in body or "volatility" in body),
        "feedback_constructive_and_harsh": _feedback_ok(pm.get("feedback", {})),
    }
    return _score("dialogue_complete", checks, threshold)


# ------------------------------------------------------------------ text

def narrative_faithfulness(run, threshold=1.0):
    texts = agent_texts(run)
    if not texts:
        return _missing("narrative_faithfulness", threshold, "agent texts")
    index = run.number_index()
    bad = {where: nums for where, t in texts if (nums := unsupported_numbers(t, index))}
    checks = {"every_number_traceable": not bad, "texts_found": len(texts) >= 20}
    return _score("narrative_faithfulness", checks, threshold, unsupported=bad, texts=len(texts))


def compliance_language(run, threshold=1.0):
    texts = agent_texts(run)
    team = run.json("team.json")
    bios = [("bio", m["bio"]) for m in (team or {}).get("members", [])]
    banned = {where: hits for where, t in texts + bios if (hits := banned_phrases(t))}
    personas = {where: hits for where, t in texts if (hits := persona_mentions(t, team))}
    checks = {"no_banned_phrases": not banned, "no_persona_names_outside_team_pages": not personas}
    return _score("compliance_language", checks, threshold, banned=banned, personas=personas)


# ------------------------------------------------------------------ harness

def cost_accounting(run, threshold=1.0):
    m = run.json("manifest.json")
    if not m or "cost_by_tool" not in m:
        return _missing("cost_accounting", threshold, "manifest cost_by_tool")
    tool_cost = sum(r["cost_usd"] for r in m["cost_by_tool"].values())
    agent_cost = sum(m["cost_by_agent_usd"].values())
    tool_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in m["cost_by_tool"].values())
    total_tokens = sum(m["usage_tokens"].values())
    rounding = 0.0001 * (len(m["cost_by_tool"]) + 1)
    checks = {
        "tool_costs_sum_to_total": abs(tool_cost - m["cost_usd"]) <= rounding + 1e-9,
        "agent_costs_sum_to_total": abs(agent_cost - m["cost_usd"]) <= 0.0001 * (len(m["cost_by_agent_usd"]) + 1),
        "tool_tokens_sum_to_total": abs(tool_tokens - total_tokens) <= 2 * len(m["cost_by_tool"]),
        "every_agent_has_call_counts": set(AGENT_NAMES) <= set(m.get("tool_calls", {})),
    }
    return _score("cost_accounting", checks, threshold, tool_cost=tool_cost, total=m["cost_usd"])


HOOK_ATTACKS = [("save_note", {"path": "../outside.txt"}), ("save_note", {"path": "C:/Windows/system32/x.txt"}),
                ("save_note", {"path": "~/secrets.txt"}), ("delete_run", {}),
                ("run", {"cmd": "rm -rf runs"}), ("run", {"cmd": "import shutil; shutil.rmtree('data')"})]
HOOK_BENIGN = [("add_slide", {"title": "50/30/20 in SPY/QQQ", "bullets": ["The PM removed one strategy."]}),
               ("save_note", {"path": "runs/x/notes.md"})]


def hook_enforcement(run, threshold=1.0):
    m = run.json("manifest.json")
    if not m:
        return _missing("hook_enforcement", threshold, "manifest.json")
    hooks = m.get("hooks") or {}
    live = default_hooks()
    attacks_blocked = all(live.before("eval", t, i) for t, i in HOOK_ATTACKS)
    benign_allowed = not any(live.before("eval", t, i) for t, i in HOOK_BENIGN)
    # No successful tool call in this run carried an input that the hooks would have denied.
    leaked = [e["tool"] for e in run.trace() if e.get("type") == "tool" and e.get("ok")
              and live.before(e["agent"], e["tool"], e.get("input") or {})]
    checks = {"pre_hooks_installed": {"forbid_delete", "confine_paths"} <= set(hooks.get("pre", [])),
              "attacks_blocked": attacks_blocked, "benign_allowed": benign_allowed, "no_denied_input_ran": not leaked}
    return _score("hook_enforcement", checks, threshold, denials=len(hooks.get("denials", [])), leaked=leaked)


# ------------------------------------------------------------------ PDF

def pdf_structure(run, threshold=1.0):
    pages, deck = run.pdf_pages(), run.json("deck.json")
    if not pages or not deck:
        return _missing("pdf_structure", threshold, "presentation.pdf or deck.json")
    from pypdf import PdfReader
    meta_title = PdfReader(str(run.dir / "presentation.pdf")).metadata.title
    sections = {s["section"] for s in deck["slides"]}
    # Titles and bullets, exactly the text the Presentation Agent's build-time rule checks (a trial failed when the
    # scorer read bullets only and "Diversifying" was in the title).
    div_text = " ".join(" ".join([s["title"], *s["bullets"]]) for s in deck["slides"]
                        if s["section"] == "diversification").lower()
    table_pages = [p for p in pages if p.lstrip().startswith(TABLE_PAGE_PREFIX)]
    checks = {
        "title": meta_title == TITLE and TITLE in pages[0],
        "first_page_explains_agents": "How AI agents produced this presentation" in pages[0]
                                      and "back-and-forth" in pages[0],
        "flowchart_page": any("The Agentic Workflow" in p for p in pages[1:3]),
        "harness_and_hooks_page": any("The Harness" in p and "Hooks" in p for p in pages),
        "guardrails_and_evals_page": any("Guardrails and Evals" in p for p in pages),
        "simulated_meeting_page": sum("simulated conversation" in p for p in pages) == 1,
        "feedback_pages": sum(p.lstrip().startswith("Constructive Feedback") for p in pages) == 1
                          and sum(p.lstrip().startswith("Harsh Feedback") for p in pages) == 1,
        "decision_log_both_rounds": any("Decision Log, Round 1" in p for p in pages)
                                    and any("Decision Log, Round 2" in p for p in pages),
        "analysis_tables_two_pages": len(table_pages) == 2,
        "every_section_present": set(SECTIONS) <= sections,
        "diversification_marketing": "diversif" in div_text,
        "team_pages": sum("Digital Investment Team" in p for p in pages) == 2,
        "disclosures_last": "Important Disclosures" in pages[-1],
        "page_count": 16 <= len(pages) <= 32,
    }
    return _score("pdf_structure", checks, threshold, pages=len(pages), table_pages=len(table_pages))


def pdf_disclosures(run, threshold=1.0):
    pages = run.pdf_pages()
    if not pages:
        return _missing("pdf_disclosures", threshold, "presentation.pdf")
    perf = "Hypothetical backtested performance"
    numeric = [i for i, p in enumerate(pages[1:-1], start=1) if re.search(r"\d+\.\d%", p)]
    last = pages[-1]
    checks = {
        "perf_footer_on_every_numeric_page": all(perf in pages[i] for i in numeric),
        "footer_on_every_page": all(("For discussion purposes only" in p) or (perf in p) for p in pages),
        "costs_disclosed": "exclude trading costs" in last,
        "hindsight_disclosed": "hindsight" in last,
        "simulated_and_ai_disclosed": "simulated" in last and FICTIONAL_LABEL in last,
        "hypothetical_on_first_page": "Hypothetical backtested results" in pages[0],
    }
    return _score("pdf_disclosures", checks, threshold, numeric_pages=len(numeric))


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
        "team_page_titles_say_fictional": sum("Digital Investment Team" in p and "(AI-generated, fictional)" in p
                                              for p in pages) == 2,
    }
    return _score("team_quality", checks, threshold, validation_error=err)


PITCH_MAIN_TITLES = ("The Top Strategy:", "Performance:", "The Team:", "Investment Process",
                     "Investment Process: Portfolio Manager and Analyst Dialogue", "Constructive Feedback",
                     "Harsh Feedback", "Token Counts and Costs per Tool", "Evals, Hooks, Harness and Guardrails",
                     "Compliance", "Disclosures")


def _cost_page_ok(run, main):
    """The pitchbook's cost page shows the manifest's total cost and its most expensive tool."""
    m = run.json("manifest.json") or {}
    page = next((p for p in main if p.lstrip().startswith("Token Counts and Costs per Tool")), "")
    if not m.get("cost_by_tool") or not page:
        return False
    top_tool, top_row = next(iter(m["cost_by_tool"].items()))
    return f"${m['cost_usd']:.3f}" in page and top_tool in page and f"${top_row['cost_usd']:.3f}" in page


def pitchbook_structure(run, threshold=1.0):
    """The pitchbook has its main pages in order, and its appendix holds every unused presentation page."""
    from pypdf import PdfReader
    pdf = run.dir / "pitchbook.pdf"
    if not pdf.exists() or not (run.dir / "presentation.pdf").exists():
        return _missing("pitchbook_structure", threshold, "pitchbook.pdf or presentation.pdf")
    pages = [re.sub(r"\s+", " ", p.extract_text() or "") for p in PdfReader(str(pdf)).pages]
    deck = [p.strip()[:60] for p in run.pdf_pages()]          # the presentation's pages, by their opening text
    appendix_at = next((i for i, p in enumerate(pages) if p.lstrip().startswith("Appendix Section")), None)
    main = pages[1:appendix_at] if appendix_at else []
    order = [next((i for i, p in enumerate(main) if p.lstrip().startswith(t)), None) for t in PITCH_MAIN_TITLES]
    appendix = pages[appendix_at + 1:] if appendix_at else []
    # Every presentation page except the cover, the flowchart and the two feedback pages (used in the main
    # section) must appear in the appendix, matched by its first words.
    reused = ("Agentic Capital Management Strategy Presentation", "The Agentic Workflow", "Constructive Feedback",
              "Harsh Feedback")
    needed = [t for t in deck if not t.startswith(reused)]
    found = [t for t in needed if any(p.lstrip().startswith(t[:40]) for p in appendix)]
    last_main = main[-1] if main else ""
    checks = {
        "title": PdfReader(str(pdf)).metadata.title == "Agentic Capital Management Pitchbook",
        "main_pages_in_order": None not in order and order == sorted(order),
        "main_section_is_short": 0 < len(main) <= 13,
        "cost_page_matches_manifest": _cost_page_ok(run, main),
        "zero_years_experience": any("investing experience: 0 years" in p for p in main),
        "compliance_fakes_labelled": any("FAKEGIPS" in p and "FAKECFA" in p and "fictional standards" in p for p in main),
        "disclosures_all_fake_agentic_no_risk_mgmt": all(s in last_main for s in (
            "This is all fake", "All of it is agentic", "Zero risk management", "no guarantee of future performance")),
        "appendix_has_every_unused_page": len(found) == len(needed),
    }
    return _score("pitchbook_structure", checks, threshold, missing=[t for t in needed if t not in found])


SCORERS = [run_health, data_integrity, research_coverage, research_reproducible, notebook_crosscheck, pm_protocol,
           dialogue_complete, narrative_faithfulness, compliance_language, cost_accounting, hook_enforcement,
           pdf_structure, pdf_disclosures, team_quality, pitchbook_structure]


def score_run(path):
    """Run every scorer. A scorer that crashes (e.g. on an artifact from an older version) scores 0
    with the error recorded, so one broken scorer can't hide the others' results."""
    run = Run(path)
    scores = []
    for scorer in SCORERS:
        try:
            scores.append(scorer(run))
        except Exception as exc:
            scores.append(Score(scorer.__name__, 0.0, 1.0, {"error": f"{type(exc).__name__}: {exc}"}))
    return scores


def render_pages(run_dir, pdf="presentation.pdf", zoom=1.4):
    """Render each page of a run's PDF to PNG for visual review.

    The presentation goes to <run>/pages/; any other PDF (e.g. pitchbook.pdf) to <run>/<name>-pages/.
    """
    import pymupdf
    run_dir = confine(run_dir)
    folder = "pages" if pdf == "presentation.pdf" else f"{Path(pdf).stem}-pages"
    out = confine(Path(run_dir) / folder)
    out.mkdir(exist_ok=True)
    paths = []
    for i, page in enumerate(pymupdf.open(str(confine(run_dir / pdf))), start=1):
        target = confine(out / f"page-{i:02d}.png")
        page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(str(target))
        paths.append(target)
    return paths
