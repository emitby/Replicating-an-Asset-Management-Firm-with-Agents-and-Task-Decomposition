# Agentic workflows: how the firm is replicated

An asset manager's research process becomes a sequence of agents, each with one job, a narrow toolset, and a checked hand-off. The core of this version is a **two-round loop between a Research Agent and a Portfolio Manager Agent**, like an analyst and a PM iterating on ideas.

## Task decomposition

| Firm function | Agent | Hand-off artifact | Checked by |
|---|---|---|---|
| Market data | Data Agent | `prices.csv`, `data_report.json` | `validate_data` |
| Quant research (round 1) | Research Agent | `research.json` (84 scored strategies, findings) | `validate_research(1)` |
| Portfolio management (round 1) | Portfolio Manager Agent | `pm.json` (top 5, 5 proposals) | `validate_pm(1)` |
| Quant research (round 2) | Research Agent | `research.json` (+5 strategies, findings) | `validate_research(2)` |
| Portfolio management (round 2) | Portfolio Manager Agent | `pm.json` (final 5, decisions, meeting) | `validate_pm(2)` |
| Risk and performance analytics | Analytics Agent | `analytics.json` | `validate_analytics` |
| Investor relations | Presentation Agent | `deck.json` → `presentation.pdf` | `validate_presentation` |
| (Branding) | Team Agent | `team.json` | `validate_team` |

## The back-and-forth, in one real run

From run `20261029-082045-eval1`:

1. **Research → PM.** After running all 84 strategies, the Research Agent reported:
   - the Top 1 rule with a 20-day SMA and a 15-day lookback led, at 834.9%;
   - the Top 3 mix with the same signal had the best risk profile (Sharpe 1.01, max drawdown −27.5%);
   - the long/short family failed;
   - results were sensitive to the lookback.
2. **PM → Research.** The PM selected the top 5 by total return; code confirmed the set. For each pick it wrote a rationale, a pro and a con. It then proposed 5 parameter sets to probe the edges of what worked: a 20-day lookback between the two best, 10- and 30-day SMAs, a 20-day Top 3 mix, and a 180-day SMA next to the 200-day winner.
3. **Research → PM.** Only the 20-day lookback held up, at 836.4%. Moving the SMA to 10 or 30 days roughly halved the return.
4. **PM's final call.**
   - Code applied the rule: Top 1 / 20d SMA / 20d replaced Top 3 mix / 20d SMA / 15d.
   - The PM explained each decision, including the cost of the change: the removed strategy had the best Sharpe.
   - The PM flagged the narrow peak as possible overfitting and named next steps: sub-period checks, a cost estimate, and a second look at the Top 3 mix.

In the three live trials the final line-ups were nearly identical. The loop converged on the 20-day-SMA region each time.

## Why the hand-offs are reliable

- **Hand-offs are files, checked by validators.** No agent reads another agent's memory, only its saved artifacts and messages.
- **Decisions with right answers are made in code.** The ranking and the replacement rule can't be argued with; the PM explains them.
- **Agents can't invent numbers.** Every sentence is checked against the computed results when it is saved, and again before the PDF is built.
- **Errors are recoverable.** A rejected call returns the reason, and the agent fixes it and resubmits. In the example run:
  - `save_research` was rejected twice for numbers it couldn't support (for example, a leader-change count it had computed itself);
  - `propose_strategies` was rejected once, because a 200-day SMA over 210 days couldn't trade from the window start;
  - `finalize` was rejected once, for an uncomputed number;
  - every rejection was corrected on the next turn.
- **Hooks and the sandbox bound what any tool can do,** whatever the agent asks for.

## Rebuildable output

The PDF is the last, deterministic step. Everything it needs is saved, so `build-pdf runs/<id>` re-renders it after a run without re-running the agents. For example, you can fix a slide's wording in `deck.json` or change the layout.

## Cost profile

A run takes about 5 minutes and about $1.20. The Presentation and PM agents cost the most:

- the PM re-reads its 84-row results table across turns;
- the Presentation Agent reads all metrics and the dialogue.

Per-tool costs are in [tools-and-tokens.md](tools-and-tokens.md).
