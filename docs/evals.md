# Evals

Three layers, from cheapest to most expensive.

## 1. Unit tests: `run.ps1 test`

Offline, deterministic, run on synthetic market data. They make no API calls, because agent tests use a scripted fake Claude client.

| File | Covers |
|---|---|
| `test_backtest.py` | SMA/signal against hand calculations. Next-day weights. Cost math. **No look-ahead:** shocking future prices leaves past weights and returns unchanged. **Walk-forward uses only prior data:** shocking prices from year Y on leaves the choices up to Y unchanged. Stitched weights follow the chosen MA. Reproducibility. |
| `test_analytics.py` | Max drawdown, constant-return metrics, the Sharpe formula, beta/capture against itself, window slicing, the annualization rule |
| `test_data.py` | Today's partial session dropped (regression), rate gap filling, short-history rejection, ticker allowlist, split detection |
| `test_guardrails.py` | Supported vs invented numbers, rounding precision, years and `MA200` ignored, banned phrases |
| `test_team.py` | Valid team accepted. Real firm, famous name, bad certification, two PMs, duplicate focus and short bio rejected. Look-alike firm names allowed. |
| `test_pdf_and_paths.py` | Disclosure footers on the right pages, IN-SAMPLE label, fictional stamps, page count, all chart kinds, path confinement including the Windows `\\?\` prefix, **no `import os`** |
| `test_agents.py` | Backtest preconditions. Findings rejected for an invented number, then accepted. Team retries after a real-firm rejection. Presentation guardrails (invented number plus "guaranteed" rejected, early `build_pdf` rejected). Code-decided disclosures. Turn limit, token budget, trace, cost math. |

## 2. Run scorers: `run.ps1 eval`

These score a finished run directory, the latest by default, for free. Every scorer is code-graded.

| Scorer | Gate | Checks |
|---|---|---|
| `run_health` | 100% | Status ok. All 5 agents finished. No tool crashes. Cost ≤ $15. Also reports tool calls and self-corrected errors. |
| `data_integrity` | 100% | All tickers present, no missing ETF prices, ≥15 years, recent, monotonic dates, positive prices |
| `backtest_tool_coverage` | 100% | The trace shows all 4 MAs, the walk-forward and the comparison |
| `backtest_reproducible` | 100% | Re-running the backtest from `prices.csv` reproduces `returns.csv` (max diff < 1e-10) |
| `analytics_consistency` | 100% | Recomputing every window from `returns.csv` matches `analytics.json` |
| `narrative_faithfulness` | 100% | Every number in slides and findings is supported (reports the count checked) |
| `compliance_language` | 100% | No banned phrases in slides, findings or bios |
| `pdf_disclosures` | 100% | Disclosure on every performance page, a footer on every page, disclosures page last, IN-SAMPLE label, cover marked hypothetical, cost assumption stated, partial year labeled YTD |
| `balance_and_traceability` | 100% | Every window where the strategy did worse than SPY (drawdown or Sharpe) is acknowledged on a slide. Every percentage on an agent slide appears verbatim on a code-generated table page. |
| `team_quality` | 100% | Schema valid, 1 PM + 5 analysts, PM most senior, careers plausible against graduation years, at least 3 certified members, 6 fictional stamps, 2 team pages |
| `pdf_structure` | 100% | 10–20 pages, ≥3 charts, metrics table, SPY comparison, all periods covered, trade-offs discussed, 6–12 agent slides |

## 3. Guardrail red-team: always included with `eval`

39 adversarial and benign cases in `evals/redteam.py`:

- invented returns and ratios
- computed differences
- wrong precision ("9.15%" when the true value is 9.12%)
- guarantees, "will outperform", risk-free claims
- real employers, famous names, made-up certifications, two PMs, a five-person team
- path escapes and non-allowlisted tickers
- benign look-alikes that must be **allowed**: correct rounding, drawdown magnitudes, parameters, years, hedged language

## Live evals: `run.ps1 eval --live --trials N`

This runs the whole pipeline N times (about $0.40 and 2 minutes per trial at current prices), scores each run, and reports **pass rates per scorer across trials**. Agents aren't deterministic, so a scorer that passes 3 of 3 trials is meaningful evidence, and 1 of 1 is not.

Results are saved to `evals/results/<timestamp>.json`. The exit code is non-zero if any gate fails.

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

**Final state:** 11/11 scorers pass in **3 of 3 live trials** and on the final run. 39/39 red-team cases pass. 75 unit tests pass.

The takeaway is built into this suite: code-graded evals verify what they check, so keep reviewing the rendered output, run several live trials, and turn every new finding into a check.

## Human and visual review

`run.ps1 render-pages runs/<id>` writes each page to `runs/<id>/pages/page-NN.png`. Layout quality, chart readability and whether the narrative is persuasive are judged by looking. Code can't fully grade them.
