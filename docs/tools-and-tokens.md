# Agent tools, tokens and cost per tool

Every action an agent can take is a **tool**: a Python function behind a JSON schema, defined in `strategy/agents/*_agent.py`. Every call passes through the tool hooks (see [guardrails.md](guardrails.md)).

Two measurements are available:

| | `manifest.json` → `cost_by_tool` | `evals/token_profile.py` |
|---|---|---|
| **When** | Every run, automatically | On demand, after a run |
| **How** | Attribution: each model call's tokens and dollars are split across the content it read and wrote, by owner (a tool owns its requests and results) | Exact counts from the token-counting endpoint, for every tool definition and every tool result in the trace |
| **Adds up to the total** | Yes, exactly (`cost_accounting` eval) | Not a cost split; it measures sizes |

```
python -m evals.token_profile runs/<id> --markdown out.md     # writes runs/<id>/token_profile.json
python -m evals.token_chart runs/<id> docs/images/tool-tokens.png
```

![Tokens per tool](images/tool-tokens.png)

## Example run `20261029-082045-eval1`

Total **372,366 tokens, $1.18**. Definition tokens are paid on every model call (cached after the first). Result tokens are what a tool returned. "Cost (run)" is the attributed dollar cost across the whole run. `strategy_detail` is shared by two agents, so its cost appears under both.

| Agent | Tool | Definition tokens | Calls | Result tokens (mean) | Result tokens (total) | Cost (run) |
|---|---|---|---|---|---|---|
| Data | `fetch_prices` | 252 | 1 | 298 | 298 | $0.004 |
| Data | `check_data_quality` | 92 | 1 | 530 | 530 | $0.002 |
| Data | `save_dataset` | 81 | 1 | 58 | 58 | $0.004 |
| Research | `run_grid` | 95 | 1 | 2,950 | 2,950 | $0.018 |
| Research | `strategy_detail` | 109 | 8 | 282 | 2,256 | $0.036 |
| Research | `save_research` | 174 | 4 (2 rejected) | 102 | 406 | $0.088 |
| Research | `get_proposals` | 85 | 1 | 1,767 | 1,767 | $0.016 |
| Research | `run_strategy` | 190 | 5 | 251 | 1,253 | $0.017 |
| PM | `get_results` | 103 | 2 | 6,906 | 13,812 | $0.084 |
| PM | `strategy_detail` | 100 | 9 | 211 | 1,896 | $0.036 |
| PM | `select_top5` | 218 | 1 | 70 | 70 | $0.018 |
| PM | `propose_strategies` | 317 | 2 (1 rejected) | 71 | 142 | $0.044 |
| PM | `finalize` | 213 | 2 (1 rejected) | 116 | 232 | $0.066 |
| PM | `write_meeting` | 191 | 1 | 8 | 8 | $0.028 |
| Analytics | `compute_metrics` | 172 | 4 | 1,452 | 5,810 | $0.035 |
| Analytics | `calendar_and_growth` | 96 | 1 | 1,650 | 1,650 | $0.008 |
| Analytics | `portfolio_fit` | 102 | 1 | 1,011 | 1,011 | $0.005 |
| Analytics | `save_analytics` | 131 | 1 | 19 | 19 | $0.025 |
| Team | `submit_team` | 836 | 1 | 176 | 176 | $0.064 |
| Presentation | `list_metrics` | 104 | 1 | 11,967 | 11,967 | $0.077 |
| Presentation | `get_dialogue` | 88 | 1 | 6,313 | 6,313 | $0.052 |
| Presentation | `get_team` | 74 | 0 | 0 | 0 | $0.000 |
| Presentation | `render_chart` | 133 | 6 | 33 | 196 | $0.009 |
| Presentation | `add_slide` | 254 | 11 | 37 | 407 | $0.204 |
| Presentation | `revise_slide` | 277 | 0 | 0 | 0 | $0.000 |
| Presentation | `build_deck` | 76 | 1 | 20 | 20 | $0.001 |

Context owners that are not tools:

| Owner | Cost | What it is |
|---|---|---|
| (system & tool definitions) | $0.165 | System prompts and tool schemas |
| (agent text) | $0.083 | The agents' own prose outside tool calls |

**By agent:**

| Agent | Model turns | Cost |
|---|---|---|
| Presentation | 5 | $0.406 |
| Portfolio Manager | 12 | $0.340 |
| Research | 11 | $0.206 |
| Analytics | 3 | $0.112 |
| Team | 2 | $0.078 |
| Data | 4 | $0.035 |

**Where the money goes:**
- `add_slide`: its cost is mostly output, because the slide text is written inside the tool call.
- `get_results`: its 84-row result is re-read on every later PM turn.
- `list_metrics` and `get_dialogue`: they give the Presentation Agent everything it may cite in one read.
