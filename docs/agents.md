# Agents

Five Claude agents (`claude-opus-5-5`, adaptive thinking, server-side refusal fallbacks). Each one:

- has a focused system prompt and a **least-privilege tool set**. No agent can touch another stage's data, the filesystem or the network directly.
- works through **deterministic tools that compute every number**. The agent decides what to run and how to explain it.
- gets tool errors back as `is_error` results, so it can correct itself. Preconditions are enforced in code, e.g. "check quality before saving" or "backtest every MA before saving".
- runs under a turn limit and the run-wide token budget, and every model call and tool call is traced.

| Agent | Effort | Tools | Preconditions enforced in code | Artifact |
|---|---|---|---|---|
| **Data** | low | `fetch_prices`, `check_data_quality`, `save_dataset` | Ticker allowlist (SPY, QQQ, TLT, GLD, IWM, IEF, ^IRX) and date range. Quality check before saving. Enough history for 24-month lookbacks before 2011. | `prices.csv`, `data_report.json` |
| **Backtest** | low | `run_ma_backtest`, `run_walk_forward`, `compare_candidates`, `run_momentum`, `save_backtest` | All 4 MAs, the walk-forward, the comparison and **all 4 momentum lookbacks** before saving. Parameters fixed by config. | `backtest.json`, `momentum.json`, `returns.csv` |
| **Analytics** | medium | `compute_metrics`, `rolling_analysis`, `compute_comparison`, `save_analytics` | All 5 MA windows, the rolling analysis and all 5 **comparison windows** (3M/1Y/3Y/5Y/since 2011) before saving. 5–9 findings, at least 2 on momentum, **every number verified**. | `analytics.json` |
| **Team** | low | `submit_team` | Schema, 1 PM + 5 analysts, certification allowlist, fictional employers, no famous names | `team.json` |
| **Presentation** | medium | `list_metrics`, `get_team`, `render_chart`, `add_slide`, `add_standard_page`, `build_pdf` | Each slide checked by guardrails when added. 10–20 slides. Required charts and 5 standard pages. **A Pro/Con slide per lookback covering its weaknesses vs SPY, a comparison slide, an Executive Summary verdict**, and MA/60/40 acknowledgements, all before the build. | `presentation.pdf`, `slides.json`, `charts/` |

## Why every agent uses an LLM, and what it adds

The numbers are deterministic either way. The LLM adds judgment:

- **Data:** interprets the quality report and writes the data note for downstream stages.
- **Backtest:** runs and cross-checks the candidates and explains the selection behavior.
- **Analytics:** decides what matters across windows and writes balanced findings for an investment committee.
- **Team:** writes credible, varied, role-appropriate personas.
- **Presentation:** chooses the narrative, charts and order, and writes persuasive but compliant copy.

## Display rounding contract

Tools return **display-ready values**: percentages to 1 decimal (`"12.3%"`), ratios to 2 (`0.85`), dollars rounded (`"$48,214"`). The prompts tell agents to quote values as displayed or rounded further, and never to compute differences. The faithfulness guardrail accepts a number only if it equals a stored full-precision value at the precision the text uses. For example, 12.345% may be written as "12.3%" or "12%", but not as "12.4%".

## Prompts

Each agent's prompt lives in its own module under [`strategy/agents/`](../strategy/agents/). The prompts state the job, the steps, and the rules that code also enforces, so the model knows the constraints rather than discovering them through rejections.
