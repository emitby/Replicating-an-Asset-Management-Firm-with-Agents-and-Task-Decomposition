"""Strategy and pipeline parameters. Every number the agents may cite that isn't
a computed result comes from here."""

from dataclasses import asdict, dataclass, field

RISK_ASSET = "SPY"
SAFE_ASSET = "IEF"
RATE_TICKER = "^IRX"          # 13-week T-bill yield, % annualized: the risk-free rate
MOMENTUM_UNIVERSE = ("SPY", "QQQ", "TLT", "GLD", "IWM", "IEF")
ALLOWED_TICKERS = tuple(dict.fromkeys((*MOMENTUM_UNIVERSE, RISK_ASSET, SAFE_ASSET, RATE_TICKER)))

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


@dataclass(frozen=True)
class MomentumConfig:
    """Monthly relative momentum: hold the single best trailing performer for the next month.
    Each lookback is a separate sub-strategy. If all trailing returns are negative, that
    sub-strategy holds cash at 0% for `cash_months` months, then resumes."""
    universe: tuple = MOMENTUM_UNIVERSE
    lookbacks: tuple = (3, 6, 12, 24)        # months
    start: str = "2011-01-01"                # first invested month
    cash_months: int = 3
    cost_bps: float = 0.0                    # user decision: no modeled costs (disclosed)

    def constants(self):
        return {*self.lookbacks, self.cash_months, len(self.universe), 2011}

    def to_dict(self):
        return asdict(self)


COMPARISON_WINDOWS = {"3M": 3, "1Y": 12, "3Y": 36, "5Y": 60, "S2011": None}   # None = since momentum start


@dataclass
class PipelineConfig:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    momentum: MomentumConfig = field(default_factory=MomentumConfig)
    model: str = "claude-opus-5-5"
    max_turns_per_agent: int = 20
    token_budget: int = 3_000_000          # hard cap on input + output tokens per run
    offline: bool = False                  # use cached prices instead of Yahoo Finance
