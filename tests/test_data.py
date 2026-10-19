import numpy as np
import pandas as pd
import pytest

from strategy.data import DataError, clean, quality_report, synthetic_prices, validate_tickers


def test_clean_drops_todays_partial_session():
    """Regression: a run during market hours used an intraday price as the last 'close'."""
    df = synthetic_prices(years=12)
    today = pd.Timestamp.today().normalize()
    df.index = pd.bdate_range(end=today, periods=len(df))
    out = clean(df)
    assert out.index.max() < today
    assert len(out) == len(df) - (1 if df.index.max() == today else 0)


def test_clean_fills_rate_gaps_and_drops_missing_etf_days():
    df = synthetic_prices(years=12)
    df.iloc[10, df.columns.get_loc("^IRX")] = np.nan
    df.iloc[20, df.columns.get_loc("IEF")] = np.nan
    out = clean(df)
    assert out["^IRX"].notna().all()
    assert df.index[20] not in out.index


def test_clean_rejects_short_history():
    with pytest.raises(DataError, match="usable rows"):
        clean(synthetic_prices(years=5))


def test_ticker_allowlist():
    assert validate_tickers(["SPY", "IEF", "SPY"]) == ["SPY", "IEF"]
    with pytest.raises(DataError):
        validate_tickers(["SPY", "QQQ"])


def test_quality_report_flags_split_like_jump():
    df = synthetic_prices(years=12)
    df.iloc[100:, df.columns.get_loc("SPY")] /= 2     # unadjusted 2:1 split
    report = quality_report(df)
    assert any("split" in i for i in report["issues"])
