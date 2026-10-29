# Hooks and guardrails

A guardrail here is a rule **enforced by code** that an agent can't talk its way past. Prompts describe every rule so agents comply on the first try, but compliance never depends on the prompt.

## Three layers of hooks

| Layer | Where | Guards against | How |
|---|---|---|---|
| **Runtime tool hooks** | `strategy/hooks.py`, called by `Agent._execute` | An agent *asking* a tool to delete something or touch a path outside the project | Pre-tool hooks run before any handler. `forbid_delete` denies tool names that imply deletion and inputs carrying delete commands (`rm`, `del`, `Remove-Item`, `os.remove`, `shutil.rmtree`, `.unlink()`, `git rm/clean`). `confine_paths` denies path-like inputs (absolute, `~`, `..`) that resolve outside the project. The post-tool hook `count_calls` records calls and errors per tool. |
| **Process sandbox** | `strategy/sandbox.py`, installed by every CLI command | Any Python code (ours or a library's) *actually doing* a forbidden file operation | A PEP 578 audit hook raises `SandboxViolation` on `os.remove`/`os.rmdir`/`shutil.rmtree`; on opening a file for writing, `mkdir`, or `rename`/`replace` outside the project; and on reading outside the project. Exceptions: reading the Python installation (imports need it), and deleting library scratch files inside `.cache/` (matplotlib removes its own lock file). |
| **Claude Code hook** | `.claude/settings.json` → `.claude/hooks/guard.py` | A developer session in this repo deleting files or reaching outside it | A PreToolUse hook on Bash, Read, Write, Edit, MultiEdit, NotebookEdit, Glob and Grep. It blocks delete commands and any path argument outside the project, with exit code 2 and the reason on stderr. |

A denied runtime call reaches the agent as an error it can act on ("Denied by the confine_paths hook: …"). It is traced as `hook_denied` and listed in the manifest. The audit hook can't be removed once installed, so its tests run in a child process.

**Known limits:**
- The Claude Code guard matches delete commands anywhere in a Bash command, including inside quoted text. For example, a `sed` script that mentions the words "git rm" is blocked. This is deliberate: a delete hidden in `bash -c "…"` must not slip through.
- The guard treats a punctuation-only argument starting with `/` (such as part of a `sed` expression) as a path, and blocks it.

## Content guardrails

| Guardrail | Enforced where | What it prevents |
|---|---|---|
| **Numeric faithfulness** (`guardrails.check_text`) | `save_research`, `select_top5`, `propose_strategies`, `finalize`, `write_meeting`, `save_analytics`, `add_slide`/`revise_slide`; again before the PDF; again in the evals | Invented or recomputed numbers. Every number must match a computed result (scores, facts shown to agents, analytics, replacement figures) or a configured parameter, at the rounding written. A PM proposal may cite its own parameters. |
| **Compliance language** | Same places, plus team bios | "guaranteed", "will outperform", "can't lose", "no risk", urgency ("act now", "why … now"), ranking overclaims, and diversification overclaims ("eliminates risk", "protects investors from drawdowns"). A negated guarantee ("does not guarantee") is allowed. |
| **Balanced marketing** | `presentation_agent.SECTION_RULES` | The diversification section must mention diversification, correlation or the blend, and carry a caveat (hindsight or years it lagged) on the same slides. This was added after a visual review found the section one-sided. |
| **Decisions by construction** | `select_top5`, `finalize`, `validate_pm` | The PM can't pick the wrong top 5 or apply the replacement rule wrongly. |
| **Comparable tests** | `validate_proposal`, `propose_strategies`, `ranking.score` | Duplicates, out-of-range parameters, and strategies that couldn't trade on every date of the common window. |
| **Required content** | `build_deck` | Every section within its slide limits, required topics (risk must mention drawdowns, costs, hindsight and the short leg), required charts. |
| **Two analysis-table pages** | `pdf.Deck.pages` (by construction) + `pdf_structure` eval | More than two pages of analysis tables. |
| **Fictional personas** | `team.validate_team`, `persona_mentions` | Real firms, famous names, fake certifications, inconsistent careers, persona names on slides. |
| **Ticker allowlist** | `data.validate_tickers` and the tool schema | Fetching anything outside the seven ETFs and ^IRX. |
| **Disclosures owned by code** | `pdf.py` | Missing footers, hypothetical/in-sample/no-cost disclosures, the simulated-meeting and AI-content notices. |

## Defense in depth

Every content rule is checked where the content is created (so the agent can fix it), again by the harness, and again by the evals on the finished PDF. Every file rule is checked by the runtime hook (agent intent), the sandbox (process behavior) and `confine()` (each read and write).
