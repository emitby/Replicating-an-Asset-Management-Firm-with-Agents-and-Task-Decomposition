"""Strategy and pipeline parameters. Every number the agents may cite that isn't
a computed result comes from here."""

from dataclasses import asdict, dataclass, field

RISK_ASSET = "SPY"
SAFE_ASSET = "IEF"
RATE_TICKER = "^IRX"          # 13-week T-bill yield, % annualized: the risk-free rate
ALLOWED_TICKERS = (RISK_ASSET, SAFE_ASSET, RATE_TICKER)

TRADING_DAYS = 252

# Analysis windows: label -> calendar months back from the last date (None = since inception)
WINDOWS = {"3M": 3, "1Y": 12, "3Y": 36, "5Y": 60, "SI": None}
ANNUALIZE_FROM_MONTHS = 12    # windows shorter than this report total return only


@dataclass(frozen=True)
class StrategyConfig:
    ma_windows: tuple = (5, 20, 50, 200)
    start: str = "2002-07-30"              # IEF inception
    cost_bps: float = 5.0                  # per unit of turnover (a full switch costs 5 bps)
    min_train_years: int = 3               # walk-forward: minimum history before the first pick
    selection_metric: str = "sharpe"
    benchmark_mix: tuple = (0.60, 0.40)    # static SPY/IEF benchmark

    def constants(self):
        """Parameter values agents may legitimately mention in prose."""
        return {*self.ma_windows, self.cost_bps, self.min_train_years,
                *(round(w * 100) for w in self.benchmark_mix), 500, 10000, 10_000}

    def to_dict(self):
        return asdict(self)


@dataclass
class PipelineConfig:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    model: str = "claude-opus-5-5"
    max_turns_per_agent: int = 20
    token_budget: int = 3_000_000          # hard cap on input + output tokens per run
    offline: bool = False                  # use cached prices instead of Yahoo Finance
