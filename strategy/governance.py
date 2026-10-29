"""Code-owned descriptions of the harness, guardrails and evals, rendered in the PDF.

These texts sit next to the code they describe and are checked against it:
`tests/test_governance.py` asserts that every eval scorer in `evals.scorers`
has exactly one entry in `EVALS` (and vice versa), and that every hook the
pipeline installs is described in `strategy.hooks.HOOK_DESCRIPTIONS`. So the
deck's governance pages can't silently drift from what actually runs.
"""

from strategy.hooks import HOOK_DESCRIPTIONS

AGENTS = (
    ("Data Agent", "Fetches the seven ETFs and the T-bill rate, checks data quality, saves the dataset."),
    ("Research Agent", "Round 1: backtests all 84 strategies. Round 2: backtests the PM's 5 proposals. Writes findings "
                       "with pros and cons for the Portfolio Manager."),
    ("Portfolio Manager Agent", "Selects the top 5 by total return, proposes 5 new parameter sets, applies the "
                                "replacement rule and explains every decision. Writes the strategy meeting and the "
                                "constructive and harsh feedback pages."),
    ("Analytics Agent", "Risk and return by period, calendar years, correlations and a SPY blend for the final 5."),
    ("Team Agent", "Creates the fictional, clearly labelled digital investment team (runs in parallel)."),
    ("Presentation Agent", "Writes the slides from the verified results; code renders the PDF."),
)

HARNESS = (
    "Deterministic Python orchestrates the agents; no LLM decides the order of work.",
    "Each stage runs one agent, then a validator checks its saved artifact before the next stage starts.",
    "Agent loop: Claude Messages API with prompt caching, concurrent tool calls, a turn limit per agent and a "
    "token budget per run; tool errors go back to the agent to fix.",
    "Trace: every model call and tool call is logged (trace.jsonl) with tokens, latency and results.",
    "Cost: tokens and dollars are attributed to each agent and each tool; the manifest records both.",
    "Artifacts: every stage saves JSON/CSV, so any stage, or just this PDF, can be rebuilt from a finished run "
    "without re-running the agents (build-pdf).",
)

GUARDRAILS = (
    ("Numeric faithfulness", "Every number an agent writes must match a computed result or a configured parameter "
                             "at the rounding used. Violations go back to the agent to fix."),
    ("Compliance language", "Promissory, risk-denying and urgency phrases are blocked (for example 'guaranteed', "
                            "'can't lose', 'act now')."),
    ("Decisions by construction", "The top-5 ranking and the replacement rule are computed in code. The Portfolio "
                                  "Manager's choices are accepted only when they match."),
    ("Comparable tests", "Every strategy is scored on the same dates. Duplicate, out-of-range or too-short-history "
                         "proposals are rejected."),
    ("Fictional personas", "Team members are AI-generated, labelled fictional on every card, and never named on "
                           "agent slides."),
    ("Ticker allowlist", "Only the seven ETFs and the T-bill rate can be fetched."),
    ("Filesystem confinement", "All reads and writes go through one confinement function; nothing is ever deleted."),
    ("Stage validators", "Each stage's output is checked before the next agent starts; every slide is re-checked "
                         "before the PDF is built."),
)

EVALS = {
    "run_health": "The run finished, every agent replied, no tool crashed, cost under the cap.",
    "data_integrity": "All seven ETFs and the T-bill rate present, positive, recent and in date order.",
    "research_coverage": "Round 1 ran all 84 strategies; round 2 ran every proposal.",
    "research_reproducible": "Recomputing every strategy from the saved prices gives identical returns and scores.",
    "notebook_crosscheck": "An independent implementation copied from the research notebook matches every strategy.",
    "pm_protocol": "Top 5 by total return, 5 valid new proposals, replacement rule applied correctly.",
    "dialogue_complete": "Research and PM messages for both rounds, decisions with pros and cons, the meeting, and the "
                         "constructive and harsh feedback scripts.",
    "narrative_faithfulness": "Every number in agent-written text is found in the computed results.",
    "compliance_language": "No promissory or urgency language; no persona names on agent slides.",
    "cost_accounting": "Per-tool and per-agent costs add up to the run's total cost.",
    "hook_enforcement": "Delete and path-confinement hooks were installed on every agent and block red-team inputs.",
    "pdf_structure": "Title, agent-process first page, flowchart, governance pages, meeting, constructive and harsh "
                     "feedback pages, decision log, at most 2 analysis-table pages, diversification section, team and "
                     "disclosures.",
    "pdf_disclosures": "Performance footer on every performance page, cost and hypothetical disclosures present.",
    "team_quality": "Six plausible fictional personas, each labelled.",
}

OTHER_EVAL_LAYERS = (
    "Unit tests for the engine, agents (with a scripted Claude client), hooks, sandbox, PDF and evals.",
    "Red-team suite: invented numbers, promissory language, rule-breaking PM inputs, delete commands and "
    "out-of-project paths must all be blocked; benign look-alikes must pass.",
    "Live trials: the full pipeline is run several times and pass rates per scorer are reported.",
)

HOOKS = HOOK_DESCRIPTIONS
