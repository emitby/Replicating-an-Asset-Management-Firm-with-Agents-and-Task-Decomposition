# Results

All results are **hypothetical backtests** from the live run of 2026-10-19, with data through the last completed session on **2026-10-16**. They're reproducible from the saved prices: the `backtest_reproducible` and `momentum_reproducible` scorers and `evals/crosscheck_momentum.py` check this. The full deck is in [example/presentation.pdf](example/presentation.pdf).

## Bottom line

- **SPY buy-and-hold beat every active approach on return and Sharpe ratio** over the common period from January 2011.
- **The MA trend strategy** was the best *risk-managed* option: the lowest volatility (12.1%), the best Sharpe among active approaches (0.67), and a max drawdown of about −26% vs SPY's −34% since 2011, or −55% since 2007. But it gave up a lot of return, and **a plain 60/40 portfolio beat it since 2007** on both return (8.4% vs 7.6%) and Sharpe (0.63 vs 0.53).
- **The best momentum variant was the 3-month lookback** (11.2% CAGR, 0.59 Sharpe, −25.9% max drawdown). The 6-month lookback was the weakest, with a −43.8% drawdown.
- **The cost asymmetry is small.** Momentum is shown before costs. Charging it 5 bps per trade lowers its CAGR by only 0.1–0.3% a year.

## Head to head since January 2011

| | CAGR | Total | Volatility | Sharpe | Sortino | Max DD | Calmar | Beta | Corr. | Up cap. | Down cap. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3-month momentum | 11.2% | 431.8% | 18.0% | 0.59 | 0.83 | −25.9% | 0.43 | 0.30 | 0.28 | 55.7% | 50.8% |
| 6-month momentum | 7.6% | 218.5% | 19.0% | 0.40 | 0.55 | −43.8% | 0.17 | 0.53 | 0.47 | 60.4% | 59.9% |
| 12-month momentum | 9.0% | 289.8% | 18.4% | 0.48 | 0.66 | −33.3% | 0.27 | 0.40 | 0.37 | 62.6% | 61.1% |
| 24-month momentum | 9.1% | 296.1% | 19.6% | 0.46 | 0.64 | −34.2% | 0.27 | 0.55 | 0.48 | 78.2% | 79.1% |
| MA trend strategy | 9.3% | 307.5% | 12.1% | 0.67 | 0.91 | −26.4% | 0.35 | 0.41 | 0.58 | 65.3% | 65.1% |
| **SPY** | **14.1%** | **699.6%** | 17.0% | **0.77** | **1.08** | −33.7% | 0.42 | 1.00 | 1.00 | 100% | 100% |

### Returns by period (3M is total; the rest are annualized)

| | 3M | 1Y | 3Y | 5Y | Since 2011 |
|---|---|---|---|---|---|
| 3-month momentum | −1.7% | 11.2% | 14.6% | 11.3% | 11.2% |
| 6-month momentum | −1.4% | 7.5% | 25.1% | 15.9% | 7.6% |
| 12-month momentum | −11.0% | 1.3% | **32.1%** | 15.1% | 9.0% |
| 24-month momentum | 4.7% | −3.6% | 16.8% | 7.4% | 9.1% |
| MA trend strategy | 1.9% | 13.0% | 18.4% | 8.1% | 9.3% |
| SPY | 1.9% | **16.8%** | 22.1% | 12.9% | **14.1%** |

Momentum has **regime-dependent leadership**. The 12-month and 6-month lookbacks beat SPY over the last 3 and 5 years, riding QQQ and GLD, but lagged badly over the last year. That's typical trend-following behavior: concentrated bets pay off when trends persist, and hurt at turning points.

### Momentum behavior

| Since 2011 | Months | Switches | Cash months | Most-held (% of months) | Holding now | CAGR at 5 bps/trade |
|---|---|---|---|---|---|---|
| 3-month | 190 | 80 | 18 | QQQ 38%, GLD 21%, IWM 16% | GLD | 10.9% |
| 6-month | 190 | 71 | 9 | QQQ 37%, IWM 21%, GLD 21% | QQQ | 7.4% |
| 12-month | 190 | 48 | 12 | QQQ 41%, GLD 18%, IWM 17% | QQQ | 8.8% |
| 24-month | 190 | 31 | 0 | QQQ 54%, GLD 21%, IWM 11% | GLD | 9.0% |

Longer lookbacks trade less and sit in QQQ more. The 24-month lookback never triggered the cash rule. The 3-month lookback went to cash most often (6 episodes, 18 months), which explains much of its shallower drawdown.

## Pros and cons by sub-strategy

These are the agents' Pro/Con slides, condensed. Every "con" covering a weakness vs SPY is **required by code**.

| | Pros | Cons |
|---|---|---|
| **3-month** | Highest momentum CAGR (11.2%) and Sharpe (0.59). Shallowest drawdown (−25.9%) thanks to frequent cash periods. Low beta (0.30). | Trailed SPY's return (14.1%) and Sharpe (0.77). Most trading (80 switches). Whipsaws at turning points. |
| **6-month** | Strong 3Y/5Y (25.1% / 15.9%) | Weakest overall: 7.6% CAGR, 0.40 Sharpe, and the **deepest drawdown (−43.8%)** |
| **12-month** | Best 3-year return of any series (32.1% a year) | 1Y only 1.3%. Drawdown about equal to SPY's. Sharpe 0.48 vs 0.77. |
| **24-month** | Fewest trades (31). Never went to cash, and steady. | Highest beta (0.55) and volatility (19.6%). Trailed SPY on every since-2011 metric. |
| **MA trend** | Lowest volatility. Best active Sharpe (0.67). Halved SPY's 2007–09 drawdown. | Trailed SPY on return everywhere. Trailed 60/40 since 2007. Worse drawdown than SPY over 5Y (2022: stocks and bonds fell together). |

## MA trend strategy since 2007 (its own history)

| Since 2007 | MA strategy | SPY | 60/40 |
|---|---|---|---|
| CAGR | 7.6% | 10.9% | 8.4% |
| Volatility | 12.4% | 19.5% | 11.2% |
| Sharpe | 0.53 | 0.55 | 0.63 |
| Max drawdown | −26.4% | −55.2% | −31.4% |
| Growth of $10,000 | $42,495 | $77,253 | $48,905 |

The walk-forward chose the 200-day MA in 16 of 20 years and the 50-day in 4.

## Caveats

- **Hypothetical:** prices come from Yahoo Finance via yfinance, with close-to-close execution, and no fees or taxes.
- **Momentum excludes trading costs** (see the sensitivity above), and assumes cash earns 0%. That understates cash returns in 2023–24.
- **QQQ dominance:** the momentum results lean heavily on QQQ's 2011–2026 run. A different period, or a universe without QQQ, could look very different.
- **Single-sample:** one 15.8-year path, with no out-of-sample test of the momentum lookback choice itself. All four lookbacks are reported, rather than picking the best.
