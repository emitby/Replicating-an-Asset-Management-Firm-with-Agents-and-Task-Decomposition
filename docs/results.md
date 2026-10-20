# Results

All results are **hypothetical backtests** with data through the last completed session, **2026-10-16**. They're reproducible from the saved prices: the `backtest_reproducible` and `momentum_reproducible` scorers and the standalone `evals/crosscheck_momentum.py` check this. The full deck is in [example/presentation.pdf](example/presentation.pdf).

> **Momentum v3 (current): always fully invested.** Each month, every lookback (1/3/6/12/24) holds **50% / 30% / 20% in its top three** ETFs by trailing return. It **never holds cash**, even when the top three or all six have negative trailing returns. v2 had two cash rules (a negative slot went to cash, and all-negative triggered a 3-month cash lock); its results are shown below for comparison. v1 (100% in the top asset) is in the git history.

## Bottom line (January 2011 to October 2026)

- **QQQ buy-and-hold still beat every approach** on return (18.7% CAGR) and Sharpe (0.86), with the deepest drawdown (−35.1%). SPY was second on return (14.1%).
- **Removing cash raised momentum returns but deepened drawdowns.**
  - CAGR rose for 4 of 5 lookbacks. The biggest change was the 1-month lookback, from 7.3% to 10.9%.
  - Max drawdowns got worse for every lookback except the 24-month, which rarely used cash anyway. The 1-month went from −22.8% to −32.9%.
- **The best momentum lookback is now 3 months:** 11.9% CAGR and a 0.77 Sharpe (equal to SPY's 0.77, below QQQ's 0.86), with a −24.1% max drawdown, shallower than SPY (−33.7%) and QQQ (−35.1%).
- **No momentum lookback beat SPY or QQQ on return.** All five had lower volatility (13.7–15.2%) than either benchmark.
- **The MA trend strategy** (9.3% CAGR, 0.67 Sharpe, −26.4% max drawdown) is unchanged.
- **The cost asymmetry is small.** Momentum is shown before costs. Charging it 5 bps per unit of turnover lowers its CAGR by 0.1–0.3% a year.

## Head to head since January 2011 (v3)

| | CAGR | Total | Volatility | Sharpe | Max DD |
|---|---|---|---|---|---|
| 1-month momentum | 10.9% | 413.7% | 13.7% | 0.71 | −32.9% |
| **3-month momentum** | **11.9%** | 487.3% | 13.9% | **0.77** | **−24.1%** |
| 6-month momentum | 11.0% | 416.2% | 13.9% | 0.71 | −27.8% |
| 12-month momentum | 9.2% | 298.5% | 14.3% | 0.58 | −30.6% |
| 24-month momentum | 11.0% | 418.0% | 15.2% | 0.66 | −28.8% |
| MA trend strategy | 9.3% | 307.5% | 12.1% | 0.67 | −26.4% |
| SPY | 14.1% | 699.6% | 17.0% | 0.77 | −33.7% |
| **QQQ** | **18.7%** | **1391.0%** | 20.7% | **0.86** | −35.1% |

The deck's *Head to Head* page adds Sortino, Calmar, beta, correlation and capture ratios for every series.

### v3 (always invested) vs v2 (cash rules), since 2011

| | v3 CAGR | v2 CAGR | v3 Sharpe | v2 Sharpe | v3 Max DD | v2 Max DD |
|---|---|---|---|---|---|---|
| 1-month | **10.9%** | 7.3% | **0.71** | 0.52 | −32.9% | **−22.8%** |
| 3-month | **11.9%** | 10.6% | **0.77** | 0.71 | −24.1% | **−22.4%** |
| 6-month | 11.0% | **11.8%** | 0.71 | **0.79** | −27.8% | **−20.8%** |
| 12-month | **9.2%** | 9.0% | 0.58 | 0.58 | −30.6% | **−22.5%** |
| 24-month | **11.0%** | 10.3% | **0.66** | 0.62 | −28.8% | −28.8% |

The trade-off is clear. Cash rules protected against drawdowns, especially for short lookbacks that triggered them often, but cost return in recoveries. The 6-month lookback is the exception: its cash periods added value.

### Returns by period (v3; 3M is total, the rest are annualized)

| | 3M | 1Y | 3Y | 5Y | Since 2011 |
|---|---|---|---|---|---|
| 1-month momentum | −0.2% | 11.7% | 23.7% | 10.3% | 10.9% |
| 3-month momentum | −2.8% | 9.5% | 15.9% | 9.7% | 11.9% |
| 6-month momentum | −1.9% | 6.6% | 21.0% | 9.4% | 11.0% |
| 12-month momentum | −4.5% | 6.9% | **25.1%** | 11.8% | 9.2% |
| 24-month momentum | **2.9%** | 7.1% | 23.5% | 12.1% | 11.0% |
| MA trend strategy | 1.9% | 13.0% | 18.4% | 8.1% | 9.3% |
| SPY | 1.9% | 16.8% | 22.1% | 12.9% | 14.1% |
| QQQ | 0.7% | **18.9%** | **25.1%** | **14.7%** | **18.7%** |

### Momentum behavior since 2011 (v3)

| | Rebalances (of 190 months) | Turnover | CAGR at 5 bps | Largest average weights | Current weights (Oct 2026) |
|---|---|---|---|---|---|
| 1-month | 181 | 106.5x | 10.6% | QQQ 24%, IWM 19%, GLD 17% | QQQ 50%, SPY 30%, IEF 20% |
| 3-month | 154 | 60.0x | 11.7% | QQQ 27%, IWM 19%, SPY 18% | GLD 50%, SPY 30%, QQQ 20% |
| 6-month | 139 | 45.7x | 10.8% | QQQ 29%, IWM 19%, SPY 19% | QQQ 50%, SPY 30%, IWM 20% |
| 12-month | 117 | 33.6x | 9.1% | QQQ 31%, SPY 19%, GLD 18% | QQQ 50%, IWM 30%, SPY 20% |
| 24-month | 88 | 21.5x | 10.9% | QQQ 39%, SPY 22%, GLD 15% | GLD 50%, QQQ 30%, SPY 20% |

Turnover counts how many times the whole portfolio was traded, with the initial purchase counted as 1.0x. Shorter lookbacks rebalance almost every month.

## Pros and cons by lookback (v3)

These are condensed. Every "con" covering a weakness vs SPY is **required by code** in the deck.

| | Pros | Cons |
|---|---|---|
| **1-month** | Strong 3-year return (23.7%). Low volatility (13.7%). | Deepest momentum drawdown (−32.9%), close to SPY's. Heaviest turnover (106.5x). Return well below SPY. |
| **3-month** | Best momentum CAGR (11.9%) and Sharpe (0.77, equal to SPY's). Shallowest momentum drawdown (−24.1%). | Return still well below SPY (14.1%) and QQQ (18.7%). Weak last 3 years (15.9%). |
| **6-month** | Solid 11.0% CAGR and 0.71 Sharpe | Worse than v2 on every measure since 2011. Trails SPY on return and Sharpe. |
| **12-month** | Best 3-year return among lookbacks (25.1%, equal to QQQ's) | Lowest momentum CAGR (9.2%) and Sharpe (0.58). Drawdown (−30.6%) close to SPY's. |
| **24-month** | Lowest turnover (21.5x). Strong recent 5-year return (12.1%). | Highest momentum volatility (15.2%). Trails SPY on return (11.0% vs 14.1%) and Sharpe (0.66 vs 0.77). |

**Common con (v3):** with no cash rule, momentum has no mechanism to step aside in broad sell-offs. In months when all six ETFs are falling, it still holds the three falling least.

## MA trend strategy since 2007 (its own history)

| Since 2007 | MA strategy | SPY | 60/40 |
|---|---|---|---|
| CAGR | 7.6% | 10.9% | 8.4% |
| Volatility | 12.4% | 19.5% | 11.2% |
| Sharpe | 0.53 | 0.55 | 0.63 |
| Max drawdown | −26.4% | −55.2% | −31.4% |
| Growth of $10,000 | $42,495 | $77,253 | $48,905 |

The walk-forward chose the 200-day MA in 16 of 20 years and the 50-day in 4. A plain 60/40 portfolio beat the MA strategy since 2007 on both return and Sharpe.

## Caveats

- **Hypothetical.** Prices come from Yahoo Finance via yfinance, with monthly rebalancing at month-end closes and no fees or taxes.
- **Momentum excludes trading costs** (see the sensitivity above).
- **QQQ dominance.** QQQ is both the momentum strategies' most-held asset and the best benchmark. A period less kind to large-cap tech would look different.
- **Single sample.** One 15.8-year path. All five lookbacks are reported, and none was optimized. Comparing v2 with v3 on the same history is itself a form of selection, so treat the differences as descriptive, not predictive.
