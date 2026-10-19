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

## Strategy 2: multi-asset momentum (4 sub-strategies)

`strategy/momentum.py`

**Universe:** SPY (US large cap), QQQ (Nasdaq 100), IWM (US small cap), TLT (20+ year Treasuries), IEF (7–10 year Treasuries) and GLD (gold).

For each lookback **L ∈ {3, 6, 12, 24} months**, which is an independent sub-strategy:

```
month-end close  M_a(t) = last adjusted close of calendar month t, for each ETF a
trailing_a(t)    = M_a(t) / M_a(t − L) − 1
at each month-end t (first decision Dec 2010, first invested month Jan 2011):
    if in a cash period:            stay in cash
    elif max_a trailing_a(t) < 0:   cash for months t+1 … t+3 at a 0% return (re-evaluate at the end of t+3)
    else:                           hold 100% of argmax_a trailing_a(t) for every trading day of month t+1
```

- **No look-ahead.** The decision at month-end t uses prices up to t. The holding starts on the first trading day of t+1. Tested by perturbing future prices.
- **Daily implementation.** The output is a daily one-hot weight matrix, so the strategy's daily returns are those of the held ETF. All the existing analytics (windows, drawdowns, beta, capture) therefore apply unchanged, and the partial current month is included.
- **Cash rule, per sub-strategy.** Each lookback triggers independently, based on its own trailing returns.
- **Costs: none (user decision).** The MA strategy is net of 5 bps per switch, so comparisons favor momentum by its trading costs. The asymmetry is stated in the footer of every performance page and in the disclosures. A **cost-sensitivity table** shows momentum's CAGR if it paid the same 5 bps per trade. The effect is small, about 0.1–0.3% a year.
- **Cash at 0%** understates T-bill income in high-rate periods (e.g. 2023–24).

### Head-to-head comparison (common period)

All four lookbacks, the MA strategy and SPY are compared over **January 2011 to the last completed session**: 3M, 1Y, 3Y, 5Y and "Since 2011", using the same metric definitions as above. Code-enforced deck rules:

- **One Pro/Con slide per lookback.** Its "Con:" bullets must cover every metric (CAGR, Sharpe, max drawdown) on which that lookback did worse than SPY since 2011.
- **A comparison slide** covering momentum vs the MA strategy vs SPY.
- **An Executive Summary verdict** across both strategies.
- **60/40 acknowledgement.** If the MA strategy trailed 60/40 since 2007, a slide bullet must say so.

### Results from the live run of 2026-10-16, hypothetical (Jan 2011 to Oct 2026)

| Since 2011 | CAGR | Volatility | Sharpe | Max DD | Trades/yr* | Cash months | CAGR at 5 bps/trade |
|---|---|---|---|---|---|---|---|
| 3-month momentum | 11.2% | 18.0% | 0.59 | −25.9% | 5.1 | 18 | 10.9% |
| 6-month momentum | 7.6% | 19.0% | 0.40 | −43.8% | 4.5 | 9 | 7.4% |
| 12-month momentum | 9.0% | 18.4% | 0.48 | −33.3% | 3.0 | 12 | 8.8% |
| 24-month momentum | 9.1% | 19.6% | 0.46 | −34.2% | 2.0 | 0 | 9.0% |
| MA trend strategy | 9.3% | 12.1% | 0.67 | −26.4% | | | (already net) |
| **SPY** | **14.1%** | 17.0% | **0.77** | −33.7% | | | |

\*Switches over about 15.8 years. All four lookbacks held QQQ most often (37–54% of months), followed by GLD and IWM.

**SPY beat every active approach on return and Sharpe since 2011.** The 3-month lookback was the best momentum variant and matched the MA strategy's shallow drawdown. The MA strategy had the best Sharpe of the active approaches, with by far the lowest volatility.

## Known limitations

- **Close-to-close execution.** The signal uses the close, and the trade is assumed at the next close. Real execution adds slippage.
- **One-year re-selection, chosen by Sharpe.** Other choices, such as other metrics, frequencies or window types, give different results. They weren't optimized here, which avoids a second layer of data mining.
- **IEF isn't always defensive.** In 2022 stocks and Treasuries fell together.
- **Trend rules lag turning points.** Short MAs whipsaw in choppy markets.
- **Yahoo Finance data** hasn't been independently verified.
