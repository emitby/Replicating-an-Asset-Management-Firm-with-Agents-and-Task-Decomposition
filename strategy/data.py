"""Market data from Yahoo Finance (via yfinance), with quality checks.

Prices are dividend- and split-adjusted closes (`auto_adjust=True`), so returns
are total returns. yfinance's cache is redirected into the project (guardrail).
"""

import hashlib

import numpy as np
import pandas as pd

from strategy.config import ALLOWED_TICKERS, RATE_TICKER, RISK_ASSET, SAFE_ASSET
from strategy.paths import CACHE_DIR, DATA_CACHE_DIR, confine, write_text

RAW_CACHE = DATA_CACHE_DIR / "prices_raw.csv"
MIN_YEARS = 10


class DataError(ValueError):
    pass


def validate_tickers(tickers):
    bad = [t for t in tickers if t not in ALLOWED_TICKERS]
    if bad:
        raise DataError(f"Tickers not allowed: {bad}. Allowed: {list(ALLOWED_TICKERS)}.")
    return list(dict.fromkeys(tickers))


def fetch_prices(tickers, start, offline=False):
    """Download adjusted closes. Offline mode reads the project's cached copy."""
    tickers = validate_tickers(tickers)
    try:
        start_ts = pd.Timestamp(start)
    except ValueError:
        raise DataError(f"Invalid start date {start!r}.") from None
    if start_ts < pd.Timestamp("1990-01-01") or start_ts > pd.Timestamp.today():
        raise DataError("Start date must be between 1990-01-01 and today.")

    if offline:
        path = confine(RAW_CACHE)
        if not path.exists():
            raise DataError("Offline mode, but no cached prices yet. Run once online.")
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        missing = [t for t in tickers if t not in df.columns]
        if missing:
            raise DataError(f"Cached data lacks {missing}.")
        return df.loc[df.index >= start_ts, tickers]

    import yfinance as yf
    yf.set_tz_cache_location(str(confine(CACHE_DIR / "yfinance")))
    raw = yf.download(tickers, start=start_ts.strftime("%Y-%m-%d"), auto_adjust=True,
                      progress=False, threads=False)
    if raw is None or raw.empty:
        raise DataError("Yahoo Finance returned no data.")
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(columns={"Close": tickers[0]})
    close = close[[t for t in tickers if t in close.columns]]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    _cache_raw(close)
    return close


def _cache_raw(close):
    path = confine(RAW_CACHE)
    merged = close
    if path.exists():
        old = pd.read_csv(path, index_col=0, parse_dates=True)
        merged = close.combine_first(old)
    write_text(path, merged.sort_index().to_csv())


def quality_report(df):
    """Facts about the raw data. Problems are listed under `issues`."""
    report = {"rows": int(len(df)), "start": str(df.index.min().date()), "end": str(df.index.max().date()),
              "columns": {}, "issues": []}
    for col in df.columns:
        s = df[col]
        valid = s.dropna()
        # Missing values before a ticker's first trade (e.g. GLD launched in 2004) aren't data errors.
        live = s.loc[valid.index.min():] if len(valid) else s
        info = {"missing": int(live.isna().sum()), "first": str(valid.index.min().date()) if len(valid) else None}
        if col != RATE_TICKER and len(valid) > 1:
            rets = valid.pct_change().dropna()
            info["max_abs_daily_return"] = round(float(rets.abs().max()), 4)
            info["stale_runs_over_5d"] = int(((rets == 0).astype(int).groupby((rets != 0).cumsum()).sum() > 5).sum())
            if info["max_abs_daily_return"] > 0.25:
                report["issues"].append(f"{col}: daily move above 25%, so check for split errors")
        if col == RATE_TICKER and len(valid):
            info["min"], info["max"] = round(float(valid.min()), 3), round(float(valid.max()), 3)
            if valid.min() < -1 or valid.max() > 20:
                report["issues"].append(f"{RATE_TICKER}: yield outside plausible range")
        if info["missing"]:
            report["issues"].append(f"{col}: {info['missing']} missing values")
        report["columns"][col] = info
    gaps = df.index.to_series().diff().dt.days.dropna()
    report["max_calendar_gap_days"] = int(gaps.max()) if len(gaps) else 0
    if report["max_calendar_gap_days"] > 5:
        report["issues"].append(f"Largest gap between rows is {report['max_calendar_gap_days']} days")
    years = (df.index.max() - df.index.min()).days / 365.25
    if years < MIN_YEARS:
        report["issues"].append(f"Only {years:.1f} years of data; need at least {MIN_YEARS}")
    return report


def clean(df):
    """Keep days where both ETFs trade. Carry the T-bill yield forward over its
    own holidays, and use 0 before it exists."""
    for t in (RISK_ASSET, SAFE_ASSET, RATE_TICKER):
        if t not in df.columns:
            raise DataError(f"Dataset is missing {t}.")
    out = df.dropna(subset=[RISK_ASSET, SAFE_ASSET]).copy()
    # Yahoo returns the current session as a row while the market is open. Its "close" is
    # an intraday price, so only completed sessions (before today) are kept.
    out = out[out.index.normalize() < pd.Timestamp.today().normalize()]
    out[RATE_TICKER] = out[RATE_TICKER].ffill().fillna(0.0)
    if len(out) < MIN_YEARS * 252:
        raise DataError(f"Only {len(out)} usable rows; need about {MIN_YEARS} years.")
    if (out[[RISK_ASSET, SAFE_ASSET]] <= 0).any().any():
        raise DataError("Non-positive prices found.")
    return out


def dataset_hash(df):
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()[:16]


def synthetic_prices(years=20, seed=7):
    """Deterministic fake market for tests and offline evals."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2003-01-01", periods=years * 252)
    regime = np.sin(np.arange(len(idx)) / 400.0)
    spy = 100 * np.exp(np.cumsum(0.0003 + 0.0006 * regime + 0.011 * rng.standard_normal(len(idx))))
    ief = 80 * np.exp(np.cumsum(0.00015 - 0.0002 * regime + 0.004 * rng.standard_normal(len(idx))))
    irx = np.clip(2.0 + 1.5 * regime + 0.05 * np.cumsum(rng.standard_normal(len(idx))) / 10, 0, 6)
    df = pd.DataFrame({RISK_ASSET: spy, SAFE_ASSET: ief, RATE_TICKER: irx}, index=idx)
    # Momentum universe: drawn after the series above, so SPY/IEF are unchanged for older tests.
    for name, drift, vol, phase in (("QQQ", 0.0004, 0.014, 0.5), ("TLT", 0.0002, 0.009, 3.0),
                                    ("GLD", 0.0002, 0.010, 1.7), ("IWM", 0.0003, 0.015, 0.9)):
        trend = 0.0007 * np.sin(np.arange(len(idx)) / 300.0 + phase)
        df[name] = 100 * np.exp(np.cumsum(drift + trend + vol * rng.standard_normal(len(idx))))
    return df
