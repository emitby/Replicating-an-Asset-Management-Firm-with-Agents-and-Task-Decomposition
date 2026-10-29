# The harness, in detail

The harness is the deterministic code that runs the agents: the firm's "operations" function. It decides what runs when, what each agent can touch, what counts as a finished hand-off, and what gets recorded. No LLM makes these decisions.

## Stages and validators (`strategy/harness.py`)

| Stage | Agent | Validator checks |
|---|---|---|
| `data` | Data Agent | All seven ETFs and ^IRX present, no missing ETF prices |
| `research1` | Research Agent | The whole 84-strategy grid saved and scored |
| `pm1` | Portfolio Manager Agent | Top 5 equals the code ranking; 5 proposals, none repeating round 1 |
| `research2` | Research Agent | Every proposal run and scored |
| `pm2` | Portfolio Manager Agent | Final line-up equals `apply_replacement`; meeting written |
| `analytics` | Analytics Agent | Every window, portfolio fit, 5–9 findings |
| `team` | Team Agent | Six valid members (runs in parallel with the data and research stages) |
| `presentation` | Presentation Agent | PDF and `deck.json` exist; every slide re-checked by the guardrails |

After the presentation stage, the harness writes `manifest.json`. It then re-renders the PDF from the saved artifacts, so the deck's harness page shows the run's final cost. `rerun_stage` re-runs any single stage on an earlier run's artifacts.

## Runtime (`strategy/agents/runtime.py`)

- **The loop:** an append-only history and concurrent tool calls. Errors go back to the agent as `is_error` results.
- **Limits:** `max_turns` per agent (40 for Presentation, 20 for the others, 8 for Team) and a run-wide token budget (4,000,000).
- **Hooks:** `Agent(..., hooks=ctx.hooks)`. Pre-tool hooks run before argument binding and can deny a call; post-tool hooks run after every call. See [guardrails.md](guardrails.md).
- **Cost per tool:** `Trace.attribute` splits each model call's usage across content owners:
  - **input-side tokens** (fresh, cache write, cache read) go to the history segments the call re-read: system and tool definitions, the task, agent text, and each tool's requests and results, in proportion to characters;
  - **output tokens** go to the call's own text and `tool_use` blocks;
  - **pricing:** each share is priced at that call's rates, so per-tool costs add up exactly to the run's cost.

## Trace and manifest

`trace.jsonl` has one JSON event per line:

| Event | Fields |
|---|---|
| `start` | the task |
| `model` | turn, stop reason, latency, usage |
| `tool` | input, ok, latency, error, the exact result text |
| `hook_denied` | tool, hook, reason |
| `tool_crash`, `refusal`, `finish` | as named |
| `stage_start`, `stage_ok`, `run_failed` | harness events |

`manifest.json` records:

- status, version, model, strategy parameters, data hash and range, seconds;
- `usage_tokens`, `cost_usd`;
- `cost_by_agent_usd`, `tokens_by_agent`;
- **`cost_by_tool`** (input and output tokens and dollars per owner);
- **`tool_calls`** (calls and errors per agent and tool, from the post-tool hook);
- **`hooks`** (the installed pre/post hooks and every denial);
- the final strategies and the list of artifacts.

## Filesystem

| Mechanism | What it does |
|---|---|
| `paths.confine()` | Resolves every path and refuses anything outside the project |
| `paths.write_text()` | Atomic writes (temp file, then `Path.replace`) |
| `sandbox.install()` | Called by every CLI command; a process-wide audit hook (see [guardrails.md](guardrails.md)) |
| Caches | matplotlib, yfinance and pycache caches are kept in `.cache/`; tests write to `.pytest_tmp/`; nothing is deleted |

## Commands

| Command | Purpose |
|---|---|
| `run [--offline]` | Full pipeline |
| `build-pdf runs/<id> [--out name.pdf]` | Rebuild the PDF from saved artifacts (no agents, no API) |
| `stage <name> --from runs/<id>` | Re-run one stage |
| `eval [--run …] [--live --trials N]` | Scorers + red-team |
| `render-pages runs/<id>` | PDF pages → PNG |
| `test` | Unit tests |

## Configuration (`strategy/config.py`)

| Field | Value |
|---|---|
| `RankingConfig.universe` | SPY, QQQ, TLT, IEF, GLD, USO, JNK |
| `signals` | 0 (close), 20, 50, 200 |
| `lookbacks` | 15–180 days |
| `portfolios` | Top 1, Top 3 mix, Long top 3 short negatives |
| `top_n`, `n_proposals` | 5, 5 |
| `sma_range`, `lookback_range` | 5–250, 10–365 |
| `blend_weight` | 0.2 |
| `cost_bps` | 0 |
| `PipelineConfig` | model `claude-opus-5-5`, turn limit, token budget, offline flag |
