# Task 5: Agentic Capital Management (SMA-ranking strategy + Portfolio Manager loop)

Plan: `C:\Users\emitb\.claude\plans\virtual-baking-biscuit.md`. Decisions: round 1 = all 84 notebook strategies (56 long-only + 28 long/short); a round-2 strategy replaces the weakest top-5 when it beats it on total return; obsolete files removed with `git rm` (one-time user OK); hooks = runtime pre/post tool hooks + process audit hook + Claude Code PreToolUse hook.

- [x] 1. `ranking.py` engine ported from notebook cells 25/27; tests match the notebook's printed returns
- [x] 2. config/data/context; Research Agent; PM Agent (code-fixed top 5, validated proposals, replacement rule); harness stages
- [x] 3. hooks.py (pre/post tool hooks), sandbox.py (audit hook), per-tool cost and token accounting
- [x] 4a. one-page simulated meeting: PM Agent and analyst agents (Research, Analytics) on what is compared, the objective, and why the strategies were picked (user, mid-task); written by the PM Agent from real results, number-checked, labelled simulated
- [x] 4. analytics (final 5 + SPY/QQQ, correlations, blends), charts, PDF ("Agentic Capital Management Strategy Presentation"), Presentation Agent; <=2 table pages enforced
- [x] 4b. PDF independent of the pipeline (user, mid-task): agents save all deck content to `deck.json`; `build-pdf runs/<id>` re-renders from saved artifacts with no agents or API calls, so the deck can be edited and rebuilt
- [x] 5. evals: scorers, red-team, independent cross-check, token profile/chart for 6 agents
- [x] 6. `git rm` obsolete files; Claude Code hook
- [x] 7. live run + 3 live trials
- [x] 8. visual review and fixes
- [x] 9. README, docs, example PDF, images; lessons; review

## Review (Task 5)

- **Final:**
  - 150 unit tests, including a full scripted six-agent run.
  - 14/14 scorers and 74/74 red-team cases.
  - Three live trials on the final code passed **14/14 in 3 of 3** ($1.16–1.20, 293–314 s each), after one scorer fix.
  - The notebook cross-check matches all 89 strategies (largest difference 8e-16).
  - The example deck has 24 pages, from run `20261029-082045-eval1`.
- **Result (2016-05-02 to 2026-10-28, in-sample, no costs):**
  - The final 5 are all Top 1 strategies: four short-lookback 20-day-SMA or close variants, plus the slow 200-day SMA over 180 days.
  - Total returns run 611.9–836.4%, against 342.8% for SPY and 638.3% for QQQ.
  - Volatility is about 27% and drawdowns run −34% to −42%. Sharpe of 0.75–0.84 is roughly SPY's (0.76) and below QQQ's (0.86).
  - Round 2 added Top 1 / 20d SMA / 20d (836.4%), which replaced Top 3 mix / 20d SMA / 15d, the best Sharpe at 1.01.
  - An 80/20 SPY blend historically beat SPY alone on return, volatility and drawdown.
- **Defects found (visual review after a 14/14 run):**
  - a one-sided diversification section → a balance rule, shown to fail on the old deck;
  - misattributed figures → an attribution prompt rule;
  - a legend covering the drawdowns;
  - an 8-point decision log, now split over 2 pages;
  - a cost-note wording error;
  - inconsistent "Top 3" labels.

  Separately, a live trial failed on a scorer/source text mismatch; the scorer was fixed.
- **Follow-ups (user requests, 2026-10-29):**
  - Correlation with SPY is added to the scores, every agent view, and both analysis tables (Table 1 has a full 84-strategy correlation grid).
  - The PDF highlights correlation phrases in the commentary. The executive summary and diversification sections must cite correlation; the new rule was shown to fail on the previous deck.
  - New PM pages "Constructive Feedback" and "Harsh Feedback" are topic-checked in code, number-checked and labelled simulated.
  - 156 tests pass. The live run `20261029-092959-eval1` passed 14/14 and is the new example deck (26 pages).
- **Open:** the Claude Code guard flags punctuation-only "/" tokens as paths (a false positive). The fix was written, but editing the guard was denied as self-modification, so it awaits the user.

---

# Task 4: Momentum v3, always fully invested (no cash, ever)

Plan: `C:\Users\emitb\.claude\plans\piped-imagining-popcorn.md`. User: "don't send allocations to zero for any reason". Both cash rules are removed. 50/30/20 in the top three every month.

- [x] 1. `cash_rules` switch (default off) in config and momentum.py, with tests first (negative picks still held, all-negative still invested, CASH always 0)
- [x] 2. prompts, PDF text and disclosures without cash language; new check that no slide describes momentum cash (proven to fail on the v2 deck)
- [x] 3. cross-check supports both modes; live run, cross-check, evals, 3 trials
- [x] 4. visual review, docs (v1/v2/v3 table), figures vs PDF, push, CI
- [x] 5. (user, mid-task) detailed docs: harness.md, evals.md, guardrails.md (guardrail engineering: harms, enforcement, limits), tools-and-tokens.md with exact per-tool token counts and a chart (docs/images/tool-tokens.png)

## Review (Task 4)

- **Final:** 101 unit tests. 14/14 scorers and 43/43 red-team cases on the verified run (20261019-224835, $1.02, 258 s). The independent cross-check passes (5 lookbacks × 190 months, CASH always 0). Three live trials on the final code passed **14/14 scorers in 3 of 3** (each $0.82–0.92, 229–255 s), and the independent cross-check passed on all three.
- **Result, since 2011:** removing cash raised CAGR for 4 of 5 lookbacks (1-month: 7.3% → 10.9%) but deepened drawdowns (1-month: −22.8% → −32.9%). The best lookback is now 3-month (11.9% CAGR, 0.77 Sharpe, equal to SPY's). QQQ still beat everything.
- **Defects found:**
  - the deck pitched always-invested momentum as aimed at shallower drawdowns
  - no no-defense Cons
  - a tie inside a Pro
  - "1.1"
  - a duplicated ETF list
  - missing x labels
  - **a false-positive cash check plus no revise tool failed a live run.** Fixed with negation-aware matching and `revise_slide`.

---

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
