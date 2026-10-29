# Results

All results are **hypothetical, in-sample backtests** with no trading costs. They cover the common window **2016-05-02 to 2026-10-28** (the last completed session). They come from the example run `20261029-092959-eval1`, whose deck is [example/presentation.pdf](example/presentation.pdf). The scorers `research_reproducible` and `notebook_crosscheck` reproduce every number from the saved prices; the second uses the research notebook's own code.

Round 1 is deterministic, so every run sees the same 84 results and the same top 5. Round 2 depends on what the Portfolio Manager Agent proposes. Across the live trials, the round-2 entry was always a 20-day-SMA, Top 1 strategy with a lookback between 15 and 30 days.

## Round 1: the grid

The Research Agent backtested all 84 combinations. Of them, **19 beat SPY's total return and 2 beat QQQ's**.

| Family | What the grid showed |
|---|---|
| **Top 1** (100% in the leader) | Highest returns (12 of 28 beat SPY), 26.3–28.4% volatility, drawdowns −32.5% to −53.4%, correlation with SPY 0.13–0.36 |
| **Top 3 mix** (50/30/20) | 16.4–18.0% volatility, around SPY's 17.7%; 7 of 28 beat SPY; the best Sharpe (1.01, 20-day SMA, 15-day lookback); correlation with SPY 0.29–0.58 |
| **Long top 3, short negatives** | None of 28 beat SPY; drawdowns as deep as −78.8%; correlation with SPY −0.14 to 0.24 |
| **Signals** | The 20-day SMA with short lookbacks led; the 200-day SMA was the most stable across lookbacks and traded least |

For reference, QQQ's correlation with SPY is 0.93.

## The Portfolio Manager's rounds

**Top 5 selected in round 1, by total return.** Code checked the ranking.

| Strategy | Total return | vs SPY | Annual | Max DD | Vol. | Sharpe | Corr. SPY |
|---|---|---|---|---|---|---|---|
| Top 1, 20d SMA, 15d | 834.9% | +492.1% | 23.8% | −38.2% | 27.1% | 0.84 | 0.16 |
| Top 1, 20d SMA, 30d | 739.0% | +396.2% | 22.5% | −34.4% | 27.1% | 0.80 | 0.16 |
| Top 1, 200d SMA, 180d | 622.1% | +279.3% | 20.8% | −42.2% | 26.7% | 0.75 | 0.36 |
| Top 1, close, 30d | 611.9% | +269.1% | 20.6% | −37.5% | 26.7% | 0.75 | 0.13 |
| Top 3 mix, 20d SMA, 15d | 548.1% | +205.2% | 19.5% | −27.5% | 16.8% | 1.01 | 0.31 |

**The 5 proposals the PM sent back to the Research Agent.** It tested the region around what worked.

| Proposal | Hypothesis (abridged) | Total return | Corr. SPY | Result |
|---|---|---|---|---|
| Top 1, 20d SMA, **21d** | Sits between the two strongest lookbacks (15d, 30d): does the 20d SMA edge hold across that range? | 811.9% | 0.16 | **Replaced** Top 3 mix, 20d SMA, 15d |
| Top 1, **10d** SMA, 15d | A faster SMA may react sooner than the 20d leader | 303.6% | 0.18 | Below SPY |
| Top 3 mix, 20d SMA, **21d** | A diversified version of the leading signal at a middle lookback | 535.8% | 0.30 | Not selected (Sharpe 1.00) |
| Top 1, **150d** SMA, 180d | Is the slow 200d result robust to a nearby window? | 592.5% | 0.20 | Not selected |
| Top 1, close, **21d** | Is the raw-close signal robust between its strong 15d and 30d results? | 240.7% | 0.16 | Below SPY |

Under the replacement rule, one proposal beat the weakest of the top 5. Two neighbours of strong strategies collapsed below SPY: the 10-day SMA, and the close with a 21-day lookback. The PM read this as a sign that the edge is narrow and possibly overfit.

## The final line-up vs SPY and QQQ

| Strategy | Total return | vs SPY | Annual | Max DD | Vol. | Sharpe | Corr. SPY | 80/20 blend annual | Blend max DD |
|---|---|---|---|---|---|---|---|---|---|
| Top 1, 20d SMA, 15d | 834.9% | +492.1% | 23.8% | −38.2% | 27.1% | 0.84 | 0.16 | 17.8% | −28.4% |
| Top 1, 20d SMA, 21d | 811.9% | +469.1% | 23.5% | −34.4% | 27.3% | 0.82 | 0.16 | 17.7% | −28.4% |
| Top 1, 20d SMA, 30d | 739.0% | +396.2% | 22.5% | −34.4% | 27.1% | 0.80 | 0.16 | 17.5% | −28.4% |
| Top 1, 200d SMA, 180d | 622.1% | +279.3% | 20.8% | −42.2% | 26.7% | 0.75 | 0.36 | 17.0% | −29.7% |
| Top 1, close, 30d | 611.9% | +269.1% | 20.6% | −37.5% | 26.7% | 0.75 | 0.13 | 17.2% | −26.1% |
| SPY | 342.8% | — | 15.3% | −33.7% | 17.7% | 0.76 | 1.00 | 15.3% (alone) | −33.7% |
| QQQ | 638.3% | +295.5% | 21.0% | −35.1% | 22.2% | 0.86 | 0.93 | | |

**Calendar years for Top 1, 20d SMA, 15d, vs SPY:**

| Year | Strategy | SPY |
|---|---|---|
| 2017 | −0.1% | 21.7% |
| 2019 | 1.9% | 31.2% |
| 2022 | 6.4% | −18.2% |
| 2025 | 53.3% | 17.7% |
| 2026 YTD | 155.0% | 14.1% |

## Reading the results

- **Return:** every final strategy beat SPY on total return by a wide margin, and three beat QQQ.
- **Correlation:** with SPY it is low, 0.13–0.36 against QQQ's 0.93. The returns came from rotating across a macro basket of stocks, Treasuries, gold, oil and credit, not from holding equities. This is the centre of the deck's diversification case, and the PDF highlights every correlation figure in its commentary.
- **Risk:** each took more risk than SPY. Volatility was about 27% and every worst drawdown was deeper than SPY's −33.7%. On a risk-adjusted basis (Sharpe 0.75–0.84) they roughly match SPY (0.76) and trail QQQ (0.86).
- **Concentration:**
  - *In time:* much of the edge comes from 2025–2026, a gold- and oil-led period.
  - *In holdings:* the Top 1 rule holds a single ETF, and USO led about 36% of the months.
  - *Between strategies:* the short-lookback strategies behave almost like one strategy.
- **As a satellite:** because correlation with SPY is low, a 20% sleeve improved a SPY portfolio historically. Return was higher, and volatility and drawdown were lower.
- **Trust:** the strategies were selected with hindsight from 89 tested combinations, with no costs. The deck's "Harsh Feedback" page makes this case against the process. The PM's next steps:
  - out-of-sample and sub-period checks;
  - a turnover-cost estimate;
  - a second look at the removed Top 3 mix, the best risk-adjusted strategy.

## Run cost

The example run took **323 s, $1.20 and 386,383 tokens**. By agent:

| Agent | Cost |
|---|---|
| Presentation | $0.41 |
| Portfolio Manager | $0.35 |
| Research | $0.19 |
| Analytics | $0.14 |
| Team | $0.08 |
| Data | $0.04 |

The cost per tool is in [tools-and-tokens.md](tools-and-tokens.md).
