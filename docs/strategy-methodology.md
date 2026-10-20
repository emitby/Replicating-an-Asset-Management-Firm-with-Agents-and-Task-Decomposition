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

## Strategy 2: multi-asset momentum (5 sub-strategies, top-3 weighted, always invested)

`strategy/momentum.py`

**Universe:** SPY (US large cap), QQQ (Nasdaq 100), IWM (US small cap), TLT (20+ year Treasuries), IEF (7–10 year Treasuries) and GLD (gold). **Benchmarks:** SPY and QQQ buy-and-hold.

For each lookback **L ∈ {1, 3, 6, 12, 24} months**, which is an independent sub-strategy:

```
month-end close  M_a(t) = last adjusted close of calendar month t, for each ETF a
trailing_a(t)    = M_a(t) / M_a(t − L) − 1
at each month-end t (first decision Dec 2010, first invested month Jan 2011):
    rank by trailing_a(t) (ties: universe order); hold 50% / 30% / 20% in ranks 1 / 2 / 3 for month t+1
    -- always fully invested: a top-three ETF is held even if its trailing return is negative,
       and even if all six are negative (v3; "don't send allocations to zero for any reason")
```

- **Cash rules (v2, off by default).** `MomentumConfig(cash_rules=True)` reproduces v2: a slot whose ETF has a negative trailing return goes to cash, and when all six are negative the sub-strategy holds cash for 3 months. The scorers and the independent cross-check read each run's own setting from `momentum.json`.
- **Monthly rebalancing with drift.** The target weights are bought at the month-end close and drift with prices within the month, so a month's return is exactly Σ w_a × (ETF a's month-over-month return). Daily returns follow from that value path, so all the existing analytics apply unchanged, and the partial current month is included.
- **No look-ahead.** The decision at month-end t uses prices up to t, and the weights apply from the first trading day of t+1. Tested by perturbing future prices.
- **Turnover** is half the sum of absolute changes between monthly target weights, which is the fraction of the portfolio traded. The initial purchase counts as 1.0, and drift-driven rebalancing isn't counted. It's reported as a multiple of the portfolio (e.g. 60.0x since 2011).
- **Costs: none (user decision).** The MA strategy is net of 5 bps per switch, so comparisons favor momentum by its trading costs. The asymmetry is stated in the footer of every performance page and in the disclosures. The **cost-sensitivity** columns show momentum's CAGR if it paid 5 bps per unit of turnover: 0.1–0.3% a year lower.
- **One source of truth for the rule's wording.** `momentum.rule_text(config)` produces the rule description used in every agent prompt and every PDF note and disclosure. With cash rules off, a code check rejects any momentum slide that describes cash, except accurate negations like "never in cash".

### Head-to-head comparison (common period)

All five lookbacks, the MA strategy, SPY and QQQ are compared over **January 2011 to the last completed session**: 3M, 1Y, 3Y, 5Y and "Since 2011", using the same metric definitions as above. Code-enforced deck rules:

- **One Pro/Con slide per lookback.** Its "Con:" bullets must cover every metric (CAGR, Sharpe, max drawdown) on which that lookback did worse than SPY since 2011.
- **No cash language** for momentum when cash rules are off.
- **A comparison slide** covering momentum vs the MA strategy vs SPY **and QQQ**.
- **An Executive Summary verdict** across both strategies.
- **60/40 acknowledgement.** If the MA strategy trailed 60/40 since 2007, a bullet must say so, on a slide that isn't a momentum lookback slide.

Full results: [results.md](results.md). In brief, for v3: **QQQ beat everything** (18.7% CAGR, 0.86 Sharpe). The **3-month lookback** was the best momentum variant (11.9% CAGR, a 0.77 Sharpe equal to SPY's, −24.1% max drawdown). Removing cash raised most lookbacks' returns but deepened their drawdowns.

### Version history

| Version | Rule | Since-2011 result (best lookback) |
|---|---|---|
| v1 (commit `6467469`) | 100% in the top asset; lookbacks 3/6/12/24; all-negative cash lock | 3-month: 11.2% CAGR, 0.59 Sharpe, −25.9% max drawdown |
| v2 (commit `55e8f9c`) | 50/30/20 in the top three; per-slot cash and an all-negative cash lock; lookbacks 1/3/6/12/24; QQQ benchmark | 6-month: 11.8% CAGR, 0.79 Sharpe, −20.8% max drawdown |
| **v3 (current)** | **50/30/20 in the top three, always fully invested (no cash, ever); lookbacks 1/3/6/12/24; QQQ benchmark** | **3-month: 11.9% CAGR, 0.77 Sharpe, −24.1% max drawdown** |

Diversifying across three holdings cut volatility from about 18–20% (v1) to 12–15% (v2). The 3-, 6- and 24-month Sharpe ratios (0.71, 0.79, 0.62) beat v1's best (0.59). The 12-month (0.58) and the new 1-month (0.52) did not.

Removing the cash rules (v2 → v3) raised CAGR for 4 of 5 lookbacks. The biggest change was the 1-month lookback, from 7.3% to 10.9%. Max drawdowns deepened for every lookback except the 24-month, for example the 1-month from −22.8% to −32.9%. The 6-month lookback was the exception: its cash periods had added value.

## Known limitations

- **Close-to-close execution.** The signal uses the close, and the trade is assumed at the next close. Real execution adds slippage.
- **One-year re-selection, chosen by Sharpe.** Other choices, such as other metrics, frequencies or window types, give different results. They weren't optimized here, which avoids a second layer of data mining.
- **IEF isn't always defensive.** In 2022 stocks and Treasuries fell together.
- **Trend rules lag turning points.** Short MAs whipsaw in choppy markets.
- **Yahoo Finance data** hasn't been independently verified.
