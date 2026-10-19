# Task: SPY/IEF MA-rotation multi-agent research and pitch pipeline

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
