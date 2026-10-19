# Task 3: Momentum v2, with 50/30/20 top-3 allocation, a 1-month lookback and a QQQ benchmark

Plan: `C:\Users\emitb\.claude\plans\piped-imagining-popcorn.md`. Decisions:
- **replace** the top-1 rule
- **per-slot cash** (a negative top-3 asset's slot goes to cash; all six negative → a 3-month lock)
- full pipeline, then push

- [x] 1. config + momentum.py v2, with tests written first. Caught before running: constant daily weights meant daily rebalancing, so changed to monthly rebalancing with drift.
- [x] 2. analytics: QQQ in the comparison, turnover-based cost sensitivity, activity from the weight columns
- [x] 3. agents (5 lookbacks, QQQ), charts (benchmarks, allocations), PDF tables and disclosures
- [x] 4. scorers, red-team, independent cross-check rewrite
- [x] 5. live run, cross-check (all 5 lookbacks, 190 months, exact), evals, 3 live trials at 100%
- [x] 6. subagent visual review and fixes (table overlap, drawdown legibility, turnover unit, tie consistency)
- [x] 7. docs (all figures checked against the PDF), example PDF, push, CI

## Review (Task 3)

- **Final:** 95 unit tests. 14/14 scorers in 3 of 3 live trials on the final code. 43/43 red-team cases. The independent cross-check passes. The deck is 29 pages.
- **Result, since 2011:** QQQ beat everything (18.7% CAGR, 0.86 Sharpe). Every momentum lookback had a shallower drawdown than SPY and QQQ (−20.8% to −28.8%). The best momentum lookback was 6-month (11.8% CAGR, 0.79 Sharpe, −20.8% max drawdown).
- **Defects found:**
  - daily vs monthly rebalancing semantics
  - MA balance check loophole via momentum slide titles (twice, as wording varied)
  - red-team constants
  - "−0.0%"
  - **table overlap with 8 series, where the first regression test failed to catch the defect and had to be rewritten**
  - illegible 8-line drawdown chart

---

# Task 2: Multi-asset momentum (4 lookbacks), added to the pipeline

Plan: `C:\Users\emitb\.claude\plans\piped-imagining-popcorn.md`. Decisions:
- cash rule decided per sub-strategy (all 6 negative → 3 months in cash)
- no trading costs for momentum (the asymmetry with MA is disclosed)
- comparison over the common period from 2011
- one combined deck

- [x] 1. `config.py`, `data.py`: new tickers, momentum config, quality report ignores missing data before a ticker's inception
- [x] 2. `momentum.py` plus `tests/test_momentum.py`. Found a bug: the initial-purchase cost was never charged.
- [x] 3. `analytics.py`: comparison windows, using a shared `_window_metrics` helper so MA and momentum use identical definitions
- [x] 4. Agents: tools for Data, Backtest, Analytics and Presentation, plus the Team prompt
- [x] 5. PDF/charts: comparison table, momentum detail page, 4 charts, disclosures. Code-enforced pros/cons, verdict and balance checks.
- [x] 6. Evals: 3 new scorers, red-team cases. The new scorers fail on the pre-momentum run, as they should.
- [x] 7. Independent cross-check (190 months, exact match), live runs, 3 live trials at 100%
- [x] 8. Two subagent visual reviews, fixes, docs, lessons

## Review (Task 2)

- **Final:** 90 unit tests. 14/14 scorers in 3 of 3 live trials on the final code. 42/42 red-team cases. The independent cross-check passes. The example deck is 27 pages.
- **Result:** since 2011, SPY (14.1% CAGR, 0.77 Sharpe) beat every active approach. The best momentum variant was the 3-month (11.2%, 0.59, max drawdown −25.9%). The MA strategy had the best Sharpe among active approaches (0.67, lowest volatility). Charging momentum 5 bps per trade lowers its CAGR by only 0.1–0.3% a year.
- **Defects found and fixed:**
  - initial-cost bug
  - silently dropped page title
  - **false cost footer** on momentum pages
  - 60/40 omission
  - a keyword-based balance check that could be satisfied without making the claim
  - heatmap legibility, clipped subtitle, scorer heuristics
- **Known limit:** wrong *claims about* real numbers (e.g. a range with the wrong minimum) can't be caught by numeric checks. Visual review caught one, and a prompt rule now guards it.

---

# Task 1: SPY/IEF MA-rotation multi-agent research and pitch pipeline

Approved plan: `C:\Users\emitb\.claude\plans\piped-imagining-popcorn.md`. Decisions: walk-forward selection, binary switch, all five agents on Claude.

## Plan

- [x] 0. Scaffold: folder, CLAUDE.md copy (verified identical), `.venv` with `--no-cache-dir`
- [x] 1. Core (deterministic): `paths.py`, `config.py`, `data.py`, `backtest.py`, `analytics.py`. Smoke-tested on synthetic data.
- [x] 2. Output: `charts.py`, `pdf.py`, `team.py`, `guardrails.py`
- [x] 3. Agents: `agents/runtime.py` (trace, budget, cost) plus 5 agents
- [x] 4. Harness and CLI, `run.ps1`/`run.sh`. `run.ps1 test` passes.
- [x] 5. Evals: 10 scorers, red-team cases, runner
- [x] 6. Live end-to-end run. The first run passed all evals in 101 s for $0.39.
- [x] 7. Visual check by subagent. **It found issues the evals missed.** Fixed at the source, added scorers, confirmed they fail on the old run, re-ran live: all pass. Numbers recomputed independently and matched to 4 decimal places.
- [x] 8. Docs: README plus 6 docs
- [x] 9. Caches confirmed inside `.cache/`. No `os` imports. Nothing deleted.

## Review

**Final:** 75 unit tests pass. 11/11 scorers pass in 3 of 3 live trials and on the final run `20261019-140022` ($0.31, 101 s). 39/39 red-team cases pass. Two visual reviews and five rounds of live trials drove the fixes listed in docs/evals.md.

Earlier checkpoint:
- **67 unit tests pass.** **10/10 scorers pass** on live run `20261019-132419`. **34/34 red-team cases pass.**
- Two live runs, about $0.40 and about 101 s each.
- **Bugs found and fixed:**
  - intraday partial session used as a close (now completed sessions only, with a regression test)
  - Windows `\\?\` prefix breaking path confinement during concurrent chart rendering
  - deck issues from the visual review (personas named as contacts, urgency title, YTD label, cost disclosure, experience years, layout)
- **Substantive result:** out-of-sample, the strategy trailed SPY (7.6% vs 10.9% CAGR) but cut max drawdown from −55.2% to −26.4%. The deck frames it honestly as risk reduction.
- **Known orphan:** `evals/fixtures_bridge.py` reuses `tests/fixtures.py` via importlib. It works, but a shared fixtures module would be cleaner. I left it in place because the guardrails forbid deleting files.
- Not pushed to GitHub; waiting for the user.
