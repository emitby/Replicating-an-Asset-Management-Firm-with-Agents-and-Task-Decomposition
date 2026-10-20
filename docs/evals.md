# Evals: what is tested and how it works

The eval suite has **five layers**, from cheapest to most expensive:

| Layer | Command | Cost | What it proves |
|---|---|---|---|
| 1. Unit tests (101) | `run.ps1 test` | Free, offline, about 1 minute | Every computation and guardrail behaves as specified, including the agent loop (scripted fake Claude) |
| 2. Run scorers (14) | `run.ps1 eval [--run runs\<id>]` | Free | A finished run's artifacts and PDF are correct, reproducible, faithful and compliant |
| 3. Guardrail red-team (43) | Included in every `eval` | Free | The guardrails block adversarial inputs **and** allow legitimate look-alikes |
| 4. Independent cross-check | `python evals\crosscheck_momentum.py runs\<id>` | Free | Momentum results match a from-scratch re-derivation that shares no code |
| 5. Live trials, plus visual review | `run.ps1 eval --live --trials N`, `run.ps1 render-pages` | About $1 and 4–5 min per trial | Agents pass every gate **repeatedly**. A reviewer judges what code can't. |

Supporting tool: the **token profiler** (`python -m evals.token_profile runs\<id>`) measures exact token counts per tool and per agent. See [tools-and-tokens.md](tools-and-tokens.md).

Each guardrail in [guardrails.md](guardrails.md) is covered by at least one unit test **and** one scorer or red-team case.

---

## 1. Unit tests

All tests run on synthetic or fixture data with no network access. Agent tests replace the Anthropic client with a **scripted fake** (`tests/conftest.py`). The fake returns pre-written `tool_use` blocks, so the real runtime, tools, guardrails and harness run end to end with no API calls.

| File | Tests | What they verify |
|---|---|---|
| `test_backtest.py` | 8 | SMA and signal against hand calculations. Next-day weight application. Cost math. **No look-ahead:** shocking future prices leaves past weights unchanged. **Walk-forward uses only prior years.** Stitched weights follow the chosen MA. Reproducibility. |
| `test_momentum.py` | 16 | 50/30/20 to the top three. v2 per-slot cash (2 parametrized cases) and the all-negative 3-month lock with `cash_rules=True`. **v3:** negative picks are still held, all-negative months are still fully invested, and the default never holds cash. 1-month lookback. No look-ahead. Monthly rebalancing with drift. Turnover and cost (the initial buy counts as 1.0). The monthly cross-check. Summary. Insufficient history rejected. Comparison includes QQQ and all lookbacks. Weight columns match history. |
| `test_analytics.py` | 9 | Max drawdown. Constant-return metrics. Sharpe formula. Beta and capture against itself. Window slicing. Annualization rule (1Y return = total return). |
| `test_data.py` | 5 | Today's partial session dropped (regression). Rate gap filling. Short history rejected. Ticker allowlist. Split detection. |
| `test_guardrails.py` | 29 | Mostly parametrized. Supported numbers pass: rounding, absolute drawdowns, `$10,000`, `MA200`, years. Invented numbers fail. Precision must match the rounding. Banned phrases. Dates aren't numbers. Guarantee negation (allowed vs "not only is it guaranteed"). Urgency language. Persona mentions. Clean text passes. |
| `test_team.py` | 10 | Valid team accepted, with the PM sorted first. Rejected: a real firm, a famous name, an unknown certification, two PMs, a duplicate focus, a short bio, experience that contradicts career dates, the wrong team size. A look-alike firm name ("Citizens Ridge Partners") is allowed. |
| `test_pdf_and_paths.py` | 11 | Path confinement, including the Windows `\\?\` prefix. **No `import os` in any file.** Matplotlib cache confined. Disclosures, footers, IN-SAMPLE and fictional stamps on the right pages. No "−0.0%" and ratios at 2 decimals ("1.10"). The footer is true for both strategies (MA net, momentum gross). Long titles never dropped. Every code page renders its title. Table overlap detection (**proven to fail on the known-bad layout**). Every chart kind renders. |
| `test_agents.py` | 13 | Backtest preconditions (must run every candidate). Findings rejected for an invented number, then accepted. Team retries after a real-firm rejection. Presentation guardrails: invented number and "guaranteed" rejected, early `build_pdf` rejected, code-owned disclosures. Every citable percentage traceable in the PDF. Momentum section requirements. **v3:** no cash language (including the exact live sentence that was falsely rejected), `revise_slide` replaces in place with the same guardrails, and momentum isn't pitched as defensive. Momentum slides can't acknowledge MA weaknesses. Turn limit and budget. Trace and cost math. All agents use the configured model. |

**Rule for regression tests** (from `tasks/lessons.md`): a regression test must **fail on the defect** before the fix. Several tests here were rewritten after they passed on the bad artifact, the table-overlap test among them.

---

## 2. Run scorers

`evals/scorers.py`: each scorer takes a run directory and returns a `Score(name, score 0–1, threshold, details)`. Every gate is **100%**. `score_run` catches a crashing scorer and records it as 0 with the error, so one broken scorer can't hide the others.

Each scorer judges a run **by the rules it was run with**. `saved_momentum_config` rebuilds `MomentumConfig` from `momentum.json` params, and runs saved before the `cash_rules` switch are treated as v2.

| Scorer | How it works | Checks |
|---|---|---|
| `run_health` | Reads `manifest.json` and `trace.jsonl` | Status ok. All 5 agents emitted `finish`. No `tool_crash` events. Cost ≤ $15. Reports tool calls and self-corrected tool errors. |
| `data_integrity` | Loads `prices.csv` | All 7 tickers present. No missing SPY/IEF prices. ≥15 years. Last date within 10 days. Monotonic dates. Positive prices. |
| `backtest_tool_coverage` | Filters the trace for successful Backtest Agent tool calls | All 4 MAs run, walk-forward run, candidates compared. Proves the agent did the work, not just that files exist. |
| `backtest_reproducible` | Re-runs `run_all(prices, StrategyConfig())` from scratch | Strategy, SPY, 60/40 and `w_spy` columns match `returns.csv` to < 1e-10 |
| `momentum_reproducible` | Re-runs `run_all_momentum` with the run's own config | For each of the 5 lookbacks: picks identical every month, daily returns < 1e-10, `monthly_crosscheck` < 1e-10 (each month's compounded return = Σ w × ETF monthly return), first month January 2011 |
| `momentum_tool_coverage` | Trace | All 5 lookbacks run. All 5 comparison windows computed. |
| `pros_cons_coverage` | Re-runs `momentum_section_problems` on `slides.json`, plus PDF text | Pro/Con slide per lookback with the required Cons. v3 no-cash, no-defensive-claim and no-defense-Con rules. Executive Summary verdict. Comparison slide. Cost asymmetry disclosed. Head to Head and Momentum Detail pages present. **`rule_disclosed_correctly`:** "always fully invested" in the disclosures iff the run had no cash rules. |
| `analytics_consistency` | Recomputes every window with `compute_window(returns.csv)` | Every metric of every series in every window matches `analytics.json` to 1e-9 |
| `narrative_faithfulness` | Rebuilds the `NumberIndex` from the run's JSON and checks every agent text | Score = 1 − unsupported / total numbers. Reports the count checked (hundreds per run). |
| `compliance_language` | Banned phrases in slides, findings and bios. Persona names on slides. | No violations |
| `pdf_disclosures` | pypdf text per page, mapped to `slides.json` (team = 2 pages) | Performance footer on every performance page. A footer on every page. Disclosures page last. IN-SAMPLE label. Cover marked hypothetical. Cost assumption stated ("N basis points per full switch"). A partial final year labeled YTD. |
| `balance_and_traceability` | `unacknowledged_adverse` re-run. Every 1-decimal % on agent slides searched in the text of code-generated pages (`CODE_PAGE_TITLES`). | Every adverse (window, benchmark, metric) acknowledged in one bullet. Every cited percentage appears in a code table. |
| `team_quality` | `validate_team` again, plus PDF text | Schema valid. 1 PM + 5 analysts. PM most senior. Careers plausible against graduation years. ≥3 certified members. ≥6 fictional stamps. 2 team pages, both titled "(AI-generated, fictional)". |
| `pdf_structure` | pymupdf images, plus text | 14–36 pages. ≥5 charts. Metrics table. SPY mentioned ≥10×. 3M/1Y/3Y/5Y covered. Trade-offs discussed. 11–22 agent slides. Every lookback named. QQQ shown ≥10×. |

`run_evals.py` prints PASS/FAIL per scorer, with the failing details for any failure, and writes `evals/results/<timestamp>.json`. It exits with 1 if any gate or red-team case fails. With `--trials N` it also reports the **pass rate per scorer across trials**.

---

## 3. Guardrail red-team (43 cases)

`evals/redteam.py` attacks the guardrails directly, not through an agent, so each case is deterministic. It uses the **same constants as production**: an earlier version lacked the momentum constants and wrongly blocked "50%, 30% and 20%".

| Category | Cases | Must block | Must allow |
|---|---|---|---|
| Text: numbers | 11 | Invented return (14.2%), invented ratio (1.10), computed difference (3.7%), wrong precision (9.15% vs 9.12%) | Display rounding (9.1%), coarser rounding (9%), drawdown magnitude (18.7%), parameters (5/20/50/200, 5 bps, 60/40), years, ISO and written dates |
| Text: language | 16 | guaranteed; will outperform; risk-free return; can't lose; no risk; "not only is income guaranteed"; "not only is it guaranteed"; "always picks the winning asset"; "never underperforms"; "Why Consider It Now"; "Act now" | Hedged language; "not a guaranteed hedge"; "does not guarantee… no guarantee"; hedged momentum; "holds 50%, 30% and 20%" |
| Team | 8 | Real employer, famous name, made-up certification, two PMs, five members, experience contradicting dates, promissory bio | A valid fictional team |
| Personas on slides | 3 | Persona as contact; persona by surname | "The investment team reviews every signal." |
| Paths | 3 | Parent directory, `..` traversal, absolute root | — |
| Tickers | 2 | TSLA; SPY + BTC-USD | — |

Benign cases matter as much as attacks: a guardrail that blocks legitimate text strands the agent (see the v3 lesson below).

---

## 4. Independent momentum cross-check

`evals/crosscheck_momentum.py` **doesn't import** `strategy.momentum`. It re-derives everything from `prices.csv` with plain month-end arithmetic:

1. Rank the six ETFs by trailing return over the lookback (month-end closes, decided at the prior month-end).
2. Give 50/30/20 to the top three. Under v3 this is always fully invested. Cash rules are applied only if the run's `momentum.json` says `cash_rules: true`.
3. Monthly return = Σ weight × the ETF's month-over-month return.

It compares each month's weights and returns with `momentum.json` and `returns.csv`, and asserts CASH is always 0 under v3. On the final v3 run it matched **all 5 lookbacks over 190 months**.

---

## 5. Live trials and visual review

`run.ps1 eval --live --trials N` runs the full pipeline N times, in fresh run directories labeled `eval1…N`. A failed run is still scored, so it fails `run_health` instead of disappearing. Agents aren't deterministic: **3 of 3 is evidence; 1 of 1 is not.**

`run.ps1 render-pages runs\<id>` writes PNGs of every page. A reviewer, usually a subagent with the PNGs and the source JSON, checks:

- whether each claim is supported, beyond whether its numbers exist
- tone and balance
- chart readability
- layout collisions

Every finding becomes a guardrail, a scorer or a test. The history below is the record of that loop.

---

## Lessons from the first live run

The first live run passed **all 10 scorers**. A visual review of the rendered pages, done by a subagent, then found real problems:

- fictional personas named on an agent-written slide, and one listed as the investor contact, without the fictional label
- an urgency title ("Why Consider It Now")
- a partial-year bar not labeled YTD
- the trading-cost size not stated in the disclosures
- persona experience years inconsistent with their career dates
- layout issues: a header collision, scientific-notation axis ticks, and the legend covering data

For each class of problem, we added a guardrail at the source (tool-time rejection, a code-owned label, or schema validation) **and** a scorer or red-team case. We confirmed that the new scorers **fail on the old run** (compliance 0%, disclosures 71%, team 86%) before re-running. The next live run passed all of them.

A second visual review, plus repeated **live trials**, exposed more gaps. Each was fixed the same way:

| Found by | Problem | Fix |
|---|---|---|
| Review 2 | A slide quoted SPY's 1Y return as 16.8% (total) while the table showed 16.9% (annualized) | The 1Y "annual" return is defined as its total return, so there's one number |
| Review 2 | The deck led with drawdown protection, but over 5Y the drawdown and Sharpe were *worse* than SPY's | `adverse_windows()` computes every such window, `build_pdf` refuses to build until each is acknowledged, and a new scorer checks it |
| Review 2 | Cited figures (calendar years, rolling, growth) appeared in no table | A code-generated supporting-data page |
| Live trials | Intermittent: cumulative returns and worst day cited but not in any table | **Traceability by construction**: `list_metrics` exposes exactly the tabled fields, and a unit test asserts every citable percentage appears in the PDF |
| Live trials | Intermittent: "not a guaranteed hedge" in a bio flagged at eval time but never checked at submit time | Negation-aware guarantee rule, and bios checked when the team is submitted |
| Own review | The metrics footnote was silently dropped when its frame had no room | Compact tables, plus a regression test |

**Final state, MA only:** 11/11 scorers passed in 3 of 3 live trials. 39/39 red-team cases passed. 75 unit tests passed.

### Adding the momentum strategy

| Found by | Problem | Fix |
|---|---|---|
| Unit tests | Momentum's initial-purchase cost was never charged: pandas sums an all-NaN diff row to 0, so `fillna` never fired | Set the first day's turnover explicitly |
| Live run | The traceability scorer excluded the code-generated comparison page, because the agent's slide title overlapped its header | Code pages are identified by known headers (`pdf.CODE_PAGE_TITLES`), matched anywhere on the page |
| Scorer debugging | **A page title was silently missing.** A two-line title didn't fit the header frame, and ReportLab dropped it without an error. This happened on the supporting-data page since the start. | Headers shrink to fit (`KeepInFrame`), and a test asserts every code page renders its title |
| Independent cross-check | None. Picks matched for all 190 months, and total returns matched to 1e-15. | `evals/crosscheck_momentum.py`, standalone code that doesn't import the project's momentum module |
| Visual review | **The footer said "net of modeled trading costs" on momentum pages, which are gross** | The footer now states both: MA net of costs, momentum excludes costs. Regression test added. |
| Visual review | The deck never said 60/40 beat the MA strategy since 2007 | `adverse_windows` includes 60/40 since inception |
| Visual review, then own debugging | The balance check passed anyway: it matched keywords anywhere on a slide ("60/40" in one bullet, "Sharpe" in another) | Acknowledgement now requires the metric **and** the benchmark in the **same bullet** |
| Visual review | No verdict in the Executive Summary | A verdict across both strategies is required by code |
| Visual review | Cost asymmetry not quantified | Code-computed cost sensitivity (momentum CAGR at 5 bps per trade) |
| Visual review | Heatmap colors indistinguishable, cash invisible, cover subtitle clipped | Distinct hues, hatched grey cash, wrapped subtitle |
| Visual review | A wrong range ("36.9% to 63.7%" when one variant was 26.3%), and a 0.4-point tie claimed as a Pro | Prompt rules. **A known limit of code checks:** each number was real, and only the claim about them was wrong. Visual review covers this. |

### Momentum v2 (50/30/20 top-three, 1-month lookback, QQQ benchmark)

| Found by | Problem | Fix |
|---|---|---|
| Own review before running | Constant daily weights would have meant **rebalancing every day**, not monthly as requested | Monthly rebalancing with drift: targets bought at the month-end close. A month's return = Σ w × the ETF's monthly return, which is tested. |
| Own review | The MA balance check could be satisfied by momentum slides, because "12-Month Momentum" contains a 1Y window synonym | Lookback slides are excluded from MA acknowledgements, with a regression test |
| Live run | The agent titled slides "3-Month **Lookback**", which slipped past the exclusion pattern for "N-month **momentum**" | The pattern now matches "N-month" with "momentum" or "lookback", and the test covers both titles |
| Red-team | The red-team number index lacked the momentum constants, so it blocked the legitimate "50%, 30% and 20%" | The red-team uses the same constants as production |
| Data review | The 1-month lookback's 1Y return showed as **"−0.0%"** | Negative zero is formatted as 0.0%, with a test |
| Visual review | **The calendar table's QQQ column was drawn under the growth table** once there were 8 series | Columns are sized to the available width, plus an assertion and a geometric test. **The first version of the test searched for words and missed the real defect.** It was rewritten to compare table header boxes, and **confirmed to fail on the bad PDF.** |
| Visual review | Momentum drawdown chart with 8 lines was illegible | Two panels: lookbacks, and MA/benchmarks |
| Visual review | Turnover shown without a unit. The tie rule applied inconsistently between slides. "Appeal" claimed despite a lower Sharpe. | Turnover shown as "47.6x". Prompt rules for consistent ties and supported risk-adjusted claims. |

**Final state, momentum v1 (top-1):** 14/14 scorers pass in 3 of 3 live trials and on the final run. 42/42 red-team cases pass. 90 unit tests pass. The independent cross-check passes.

### Momentum v3 (always fully invested, no cash)

| Found by | Problem | Fix |
|---|---|---|
| Own review | Prompts, disclosures and footnotes each described the momentum rule separately, so a rule change could leave stale text | `rule_text(mcfg)` is the single source, used everywhere. The `rule_disclosed_correctly` eval check. |
| Visual review of the first v3 run | **The deck pitched always-invested momentum as "aimed at shallower drawdowns"** on 4 pages. It has no defensive mechanism. | `DEFENSIVE_CLAIM_RE`, checked **per bullet** so true MA statements on shared slides pass. A required no-defense `Con:` per lookback (`NO_DEFENSE_RE`). Both were proven to flag exactly the bad slides of that run. |
| Visual review | A tie claimed inside a Pro. Ratios printed as "1.1". A duplicated ETF list in the disclosures. Missing x-axis labels on the top drawdown panel. | Prompt tie rule (never in a Pro; same cost basis). Ratios always at 2 decimals, with a test. Disclosures use `rule_text` once. `labelbottom=True`. |
| **Live run failure** | "Presentation Agent did not build the PDF". The cash check, a lookbehind regex, rejected the *true* sentence "it never holds cash and has no defensive mechanism", and the agent had no way to edit an existing slide. It stopped without a deck, and the run failed. | Negation-aware `_CashMention` (a negation within 40 characters before "cash"). A new `revise_slide` tool with the same `validated()` checks. Regression tests use the exact live sentence. |
| Token profiler | Tool results, not definitions, drive cost. `list_metrics` (8.8K tokens) sits in the Presentation context for 13 turns. | Documented in [tools-and-tokens.md](tools-and-tokens.md). Not optimized, at about $1 per run. |

**Final state, momentum v3:** the verified run (`20261019-224835`, $1.02, 258 s) passes 14/14 scorers. 43/43 red-team cases pass. 101 unit tests pass. The independent cross-check passes (5 lookbacks × 190 months, CASH always 0). The Presentation Agent self-corrected through `revise_slide` 4 times. Three live trials on the final code passed **14/14 scorers in 3 of 3** (each $0.82–0.92, 229–255 s), and the independent cross-check passed on all three.

The takeaway is built into this suite: code-graded evals verify what they check, so keep reviewing the rendered output, run several live trials, and turn every new finding into a check. **And test the guardrails' false positives as hard as their false negatives.**
