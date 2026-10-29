# Strategy methodology

The strategy comes from the research notebook `download_prices.ipynb` (sections "Rank on the moving average instead of the close" and "Long the top 3, short the losers"). `strategy/ranking.py` ports it with identical semantics, and `evals/crosscheck_ranking.py` re-runs the notebook's own code against every result.

## The rule

At each **month end**, the last trading day of each calendar month (excluding the current, unfinished month):

1. **Signal:** for each ETF in the universe (SPY, QQQ, TLT, IEF, GLD, USO, JNK), take the adjusted close or its N-trading-day simple moving average (SMA). The SMA only drives the ranking; returns are always earned on the actual close.
2. **Score:** the signal's % change over a trailing lookback of D calendar days. The past value is the signal on the last trading day on or before (month end − D).
3. **Portfolio:** one of three rules.

   | Rule | Holdings |
   |---|---|
   | **Top 1** | 100% in the top-ranked ETF |
   | **Top 3 mix** | 50% / 30% / 20% in the top three |
   | **Long top 3, short negatives** | The Top 3 mix, plus an equal-weight short (100% in total) of every other ETF with a negative score; with none, the month is long only. Short P&L is measured on the entry price, and borrow costs are ignored. |

4. **Holding:** bought at the month-end close and held to the next month end. Weights drift with prices within the month.

`strategy.ranking.rule_text` is the single wording of this rule. Every agent prompt and the PDF disclosure use it.

## Round 1 grid and round 2 proposals

| Parameter | Round 1 grid | Round 2 proposals (PM) |
|---|---|---|
| Signal | close, 20, 50, 200-day SMA | close, or any SMA of 5–250 days |
| Lookback | 15, 30, 60, 90, 120, 150, 180 days | 10–365 days |
| Portfolio | all three | any of the three |
| Count | 84 | 5, all new |

## Comparable scoring

Longer SMAs and lookbacks need more history before their first pick. All strategies are scored over the **same window**: from the day after the latest first pick in round 1 (the 200-day SMA with a 180-day lookback, 2016-05-02) to the last completed session. Code rejects any round-2 proposal whose first trading day falls after that start. So every one of the 89 strategies is scored on identical dates, against SPY and QQQ buy & hold over the same dates.

## Metrics

| Metric | Definition |
|---|---|
| Total return | Compounded over the window |
| vs SPY | Total return minus SPY's |
| Annual return (CAGR) | (1 + total)^(252/days) − 1 |
| Volatility | Daily standard deviation × √252 |
| Max drawdown | Largest peak-to-trough fall |
| Sharpe | Mean daily excess return over the T-bill rate (^IRX) × 252 / volatility |
| Correlation | Of daily returns over the window |
| 80/20 blend | 80% SPY + 20% strategy, rebalanced daily to fixed weights |

## The Portfolio Manager's rules (enforced in code)

- **Selection:** the top 5 by total return over the window (`ranking.top_n`, with ties broken by id). The PM's selection is accepted only if it matches.
- **Replacement:** a new strategy that beats the weakest of the current top 5 replaces it, repeated until none does (`ranking.apply_replacement`). The final 5 are therefore the best 5 of all 89 by total return.

## Data

- **Source:** adjusted daily closes from Yahoo Finance (yfinance, `auto_adjust=True`) from 2015-01-01, plus the 13-week T-bill yield (^IRX).
- **Rows kept:** only days on which all seven ETFs traded, and only completed sessions. A row for today is an intraday price, so it is dropped.

## Limitations

- **In-sample selection:** the winners were chosen with hindsight from 89 strategies on one period.
- **No trading costs:** the Top 1 leaders change ETF about 90 times in 10.5 years.
- **Concentration:** Top 1 holds one ETF at a time.
- **Short leg:** the long/short variant ignores borrow costs.
- **Blend:** the blend is rebalanced daily without costs.
