# Strategy methodology

## The rule

For a moving-average length **N**:

```
signal[t]    = 1  if SPY_close[t] > SMA_N(SPY_close)[t]   else 0
weight_SPY   = signal[t-1]          # decided at yesterday's close, held today
weight_IEF   = 1 - weight_SPY
r_port[t]    = w_SPY[t]·r_SPY[t] + w_IEF[t]·r_IEF[t] − |Δw_SPY[t]| · cost_bps / 10,000
```

- **Assets.** SPY (S&P 500 ETF) is the risk asset. IEF (7–10 year Treasury ETF) is the defensive asset.
- **Prices.** Yahoo Finance adjusted closes (`auto_adjust=True`), so returns include dividends and coupons.
- **Costs.** 5 bps for each full switch, configurable as `StrategyConfig.cost_bps`. Management fees, taxes and market impact beyond that aren't modeled.
- **Candidates.** N ∈ {5, 20, 50, 200} trading days.

## Picking the best moving average without hindsight

Choosing the N with the best full-period result and then reporting that result would be **look-ahead bias**: you'd be using the future to choose the rule. Instead the strategy uses **walk-forward selection**:

1. The comparison window starts on the first day when every candidate has a valid SMA, which takes 200 days of history.
2. On the first trading day of each calendar year Y, after at least `min_train_years` (3) of history, compute each candidate's **Sharpe ratio** over all data *before* Y (an expanding window).
3. Trade the winner's signals throughout year Y.
4. Stitch the yearly choices into one out-of-sample weight series. Returns are recomputed on the stitched weights, so a change of MA at a year boundary pays its switching cost.

The resulting "Strategy" is what an investor following this procedure could actually have done. Ties go to the shorter MA.

**In-sample context.** The deck also shows each single-MA rule over the same out-of-sample period. That table is labeled **IN-SAMPLE** on the page, in the PDF footer and in the disclosures, because it uses hindsight.

## Benchmarks

| Benchmark | Definition |
|---|---|
| **SPY** (primary) | Buy-and-hold SPY over the same out-of-sample period |
| **60/40** | 60% SPY / 40% IEF, rebalanced daily, no costs |

## Metrics

All metrics are in `strategy/analytics.py`, computed over trailing windows ending on the last completed session.

| Window | Months | Annualized? |
|---|---|---|
| 3M | 3 | No: total return only |
| 1Y | 12 | Yes |
| 3Y | 36 | Yes |
| 5Y | 60 | Yes |
| SI | since the walk-forward start | Yes |

| Metric | Definition |
|---|---|
| Total return | ∏(1 + r) − 1 |
| CAGR | (1 + total)^(252 / days) − 1 |
| Volatility | stdev(r) × √252 |
| Sharpe | mean(r − r_f) × 252 / volatility, with r_f = ^IRX / 100 / 252 |
| Sortino | mean(r − r_f) × 252 / (√mean(min(r − r_f, 0)²) × √252) |
| Max drawdown | min(equity / running peak − 1) |
| Calmar | CAGR / \|max drawdown\| |
| Beta, correlation | vs SPY daily returns |
| Up / down capture | mean strategy return on SPY up (down) days ÷ mean SPY return on those days |
| Hit rate | share of days with a positive return |
| Switches, % time in SPY | from the strategy's weight series |

Also computed: rolling 1-year returns vs SPY (the share of periods beating SPY, best and worst years), growth of $10,000 and calendar-year returns.

## Data handling

- Tickers are limited to an allowlist: SPY, IEF and ^IRX.
- Only days when both ETFs traded are kept. ^IRX is carried forward over its own holidays.
- **Only completed sessions are used.** If the pipeline runs during market hours, Yahoo returns today's in-progress price, and that row is dropped. This was a bug in the first live run, and a regression test now covers it.
- Quality checks: missing values, calendar gaps over 5 days, daily moves over 25% (which suggest a split error), stale price runs, and an implausible T-bill yield.
- The dataset hash is recorded in each run's manifest for reproducibility.

## Known limitations

- **Close-to-close execution.** The signal uses the close, and the trade is assumed at the next close. Real execution adds slippage.
- **One-year re-selection, chosen by Sharpe.** Other choices, such as other metrics, frequencies or window types, give different results. They weren't optimized here, which avoids a second layer of data mining.
- **IEF isn't always defensive.** In 2022 stocks and Treasuries fell together.
- **Trend rules lag turning points.** Short MAs whipsaw in choppy markets.
- **Yahoo Finance data** hasn't been independently verified.
