# Results

All results are **hypothetical backtests** with data through the last completed session, **2026-10-16**. They're reproducible from the saved prices: the `backtest_reproducible` and `momentum_reproducible` scorers and the standalone `evals/crosscheck_momentum.py` check this. The full deck is in [example/presentation.pdf](example/presentation.pdf).

> **Momentum v2.** The momentum strategy now holds **50% / 30% / 20% in the top three** trailing performers instead of 100% in the top one. It adds a **1-month lookback**, holds **per-slot cash** for negative-momentum picks, and is benchmarked against **both SPY and QQQ**. Results for the earlier top-1 version are in the git history (commit `6467469`).

## Bottom line (January 2011 to October 2026)

- **QQQ buy-and-hold beat every approach** on return (18.7% CAGR) and Sharpe (0.86), at the cost of the deepest drawdown (−35.1%). **SPY was second** on return (14.1%).
- **Spreading momentum across the top three changed its character.** Every lookback now has a **shallower drawdown than SPY and QQQ** (−20.8% to −28.8%) and lower volatility (11.9–15.1%), but also a lower return than both benchmarks.
- **The best momentum lookback was 6 months:** 11.8% CAGR, a 0.79 Sharpe (in line with SPY's 0.77, below QQQ's 0.86) and the shallowest drawdown of any series (−20.8%).
- **The 1-month lookback was the weakest:** a 7.3% CAGR, 26.6% average cash weight, and the most turnover (105.9x the portfolio).
- **The MA trend strategy** (9.3% CAGR, 0.67 Sharpe, −26.4% max drawdown) is roughly mid-pack among the momentum lookbacks on a risk-adjusted basis.
- **The cost asymmetry is small.** Momentum is shown before costs. Charging it 5 bps per unit of turnover lowers its CAGR by 0.1–0.3% a year.

## Head to head since January 2011

| | CAGR | Total | Volatility | Sharpe | Max DD |
|---|---|---|---|---|---|
| 1-month momentum | 7.3% | 204.0% | 11.9% | 0.52 | −22.8% |
| 3-month momentum | 10.6% | 387.7% | 13.1% | 0.71 | −22.4% |
| **6-month momentum** | 11.8% | 480.7% | 13.3% | 0.79 | **−20.8%** |
| 12-month momentum | 9.0% | 290.7% | 13.8% | 0.58 | −22.5% |
| 24-month momentum | 10.3% | 368.3% | 15.1% | 0.62 | −28.8% |
| MA trend strategy | 9.3% | 307.5% | 12.1% | 0.67 | −26.4% |
| SPY | 14.1% | 699.6% | 17.0% | 0.77 | −33.7% |
| **QQQ** | **18.7%** | **1391.0%** | 20.7% | **0.86** | −35.1% |

The deck's *Head to Head* page adds Sortino, Calmar, beta, correlation and capture ratios for every series.

### Returns by period (3M is total; the rest are annualized)

| | 3M | 1Y | 3Y | 5Y | Since 2011 |
|---|---|---|---|---|---|
| 1-month momentum | −0.5% | 0.0% | 15.4% | 8.5% | 7.3% |
| 3-month momentum | −2.1% | 10.3% | 15.0% | 10.1% | 10.6% |
| 6-month momentum | −1.9% | 6.6% | 21.4% | 12.6% | 11.8% |
| 12-month momentum | −4.5% | 6.9% | **25.1%** | 12.0% | 9.0% |
| 24-month momentum | **2.9%** | 7.1% | 21.6% | 9.8% | 10.3% |
| MA trend strategy | 1.9% | 13.0% | 18.4% | 8.1% | 9.3% |
| SPY | 1.9% | 16.8% | 22.1% | 12.9% | 14.1% |
| QQQ | 0.7% | **18.9%** | **25.1%** | **14.7%** | **18.7%** |

### Momentum behavior since 2011

| | Rebalances (of 190 months) | All-cash months | Avg cash weight | Turnover | CAGR at 5 bps | Largest average weights | Current weights (Oct 2026) |
|---|---|---|---|---|---|---|---|
| 1-month | 156 | 42 | 26.6% | 105.9x | 7.0% | QQQ 19%, IWM 15%, SPY 13% | QQQ 50%, cash 50% |
| 3-month | 139 | 18 | 11.8% | 60.7x | 10.4% | QQQ 25%, IWM 17%, SPY 16% | GLD 50%, SPY 30%, QQQ 20% |
| 6-month | 136 | 9 | 6.7% | 47.6x | 11.6% | QQQ 28%, IWM 18%, SPY 17% | QQQ 50%, SPY 30%, IWM 20% |
| 12-month | 112 | 12 | 6.9% | 34.3x | 8.9% | QQQ 31%, SPY 17%, IWM 16% | QQQ 50%, IWM 30%, SPY 20% |
| 24-month | 93 | 0 | 1.1% | 23.8x | 10.2% | QQQ 38%, SPY 22%, GLD 15% | GLD 50%, QQQ 30%, SPY 20% |

Shorter lookbacks rebalance more, sit in cash more (both full-cash locks and negative slots), and trade far more. The 24-month lookback never triggered a cash lock. Turnover counts how many times the whole portfolio was traded, with the initial purchase counted as 1.0x.

## Pros and cons by lookback

These are condensed from the agents' slides. Every "con" covering a weakness vs SPY is **required by code**, and figures are taken from the tables above.

| | Pros | Cons |
|---|---|---|
| **1-month** | Lowest volatility of any series (11.9%). Shallow drawdown (−22.8%). | Weakest return (7.3%) and Sharpe (0.52). Flat over the last year (0.0%). Heavy turnover (105.9x) and 26.6% average cash. |
| **3-month** | Solid Sharpe (0.71). Drawdown about a third shallower than SPY's (−22.4% vs −33.7%). | Return well below SPY (10.6% vs 14.1%) and QQQ. Frequent rebalancing. |
| **6-month** | Best momentum return (11.8%) and Sharpe (0.79, in line with SPY's 0.77). Shallowest drawdown of all series (−20.8%). | Still trails SPY and QQQ on return, and QQQ on Sharpe (0.86). Weak last year (6.6%). |
| **12-month** | Strongest 3-year return among the lookbacks (25.1%, equal to QQQ's) | Lowest Sharpe of the longer lookbacks (0.58), and 9.0% CAGR since 2011 |
| **24-month** | Fewest rebalances and lowest turnover (23.8x). Never fully in cash. | Deepest momentum drawdown (−28.8%) and highest volatility (15.1%). Trails SPY on return (10.3% vs 14.1%) and Sharpe (0.62 vs 0.77). |

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
- **Momentum excludes trading costs** (see the sensitivity above), and cash earns 0%, which understates cash returns in 2023–24.
- **QQQ dominance.** QQQ is both the momentum strategies' most-held asset and the best benchmark. A period less kind to large-cap tech would look different.
- **Single sample.** One 15.8-year path. All five lookbacks are reported rather than picking the best, and none was optimized.
