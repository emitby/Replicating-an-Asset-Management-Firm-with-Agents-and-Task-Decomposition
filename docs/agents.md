# Agents

Six Claude agents (`claude-opus-5-5`). Each one:

- has one system prompt and a fixed set of tools;
- runs through the same loop (`agents/runtime.py`), with tool hooks, a turn limit, a run-wide token budget, and tracing of every call;
- sees only rounded, display-ready numbers (`agents/display.py`: percentages to 1 decimal, ratios to 2). The guardrails accept exactly these roundings, or coarser ones.

| Agent | Effort | Why an LLM | Tools |
|---|---|---|---|
| **Data Agent** | low | Reads the quality report and decides what is a real problem | `fetch_prices`, `check_data_quality`, `save_dataset` |
| **Research Agent** (2 rounds) | medium | Decides what to examine, interprets 84 results, writes findings with pros and cons for the PM | Round 1: `run_grid`, `strategy_detail`, `save_research`. Round 2: `get_proposals`, `run_strategy`, `strategy_detail`, `save_research` |
| **Portfolio Manager Agent** (2 rounds) | medium | Judges the trade-offs, designs the 5 new parameter sets, explains each decision, writes the meeting | Round 1: `get_results`, `strategy_detail`, `select_top5`, `propose_strategies`. Round 2: `get_results`, `strategy_detail`, `finalize`, `write_meeting` |
| **Analytics Agent** | medium | Chooses and writes the findings an investment committee reads | `compute_metrics`, `calendar_and_growth`, `portfolio_fit`, `save_analytics` |
| **Team Agent** | low | Invents a credible, varied fictional team | `submit_team` |
| **Presentation Agent** | medium | Writes the narrative, including the positive diversification section | `list_metrics`, `get_dialogue`, `get_team`, `render_chart`, `add_slide`, `revise_slide`, `build_deck` |

## What each agent decides vs what code decides

| Decision | Agent | Code |
|---|---|---|
| Which strategies to look at closely | Research, PM | |
| Which 5 are "top" | PM names them | `ranking.top_n` must agree, or the call is rejected |
| What to test next | PM proposes | `validate_proposal` plus a history check reject duplicates, out-of-range or too-short-history sets |
| Which new strategies replace which | PM explains | `ranking.apply_replacement` decides |
| Every number | | Computed by tools; text is checked against them |
| Slide wording and order within sections | Presentation | Section limits, required topics, required charts, ≤ 2 table pages |

## The Research ↔ PM dialogue

Each `save_research`, `propose_strategies` and `finalize` call appends a message to `ctx.dialogue`, which is saved as `dialogue.json`:

| From | To | Round | Content |
|---|---|---|---|
| Research Agent | Portfolio Manager Agent | 1 | Findings with ≥ 2 pros and ≥ 2 cons |
| Portfolio Manager Agent | Research Agent | 1 | Top 5 with rationale, pro and con; 5 proposals with hypothesis, pro and con |
| Research Agent | Portfolio Manager Agent | 2 | Findings on the proposals |
| Portfolio Manager Agent | All agents | 2 | Every final and removed strategy with rationale, pro and con |

The PDF renders this as the decision log. The PM's task message in each round includes the Research Agent's latest message, which is how the hand-off travels.

## The simulated meeting

`write_meeting` accepts 8–14 lines from the PM, Research and Analytics agents, and each must speak at least twice. The script must:

- cover what is being compared, the objective, SPY and risk;
- fit one page;
- pass the numeric and compliance checks.

The PDF labels it a simulated conversation in its title and subtitle, and in the disclosures.

## Prompts

Prompts live next to each agent's tools in `strategy/agents/*_agent.py`. Rules that matter are also enforced in code; the prompt states them so the agent complies on the first try. One rule was added after a visual review found an agent attaching one strategy's figure to another: name the strategy every figure belongs to, and use the true minimum and maximum for ranges.
