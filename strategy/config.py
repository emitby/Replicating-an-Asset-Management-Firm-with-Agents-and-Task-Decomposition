"""Strategy and pipeline parameters.

Every number the agents may cite that isn't a computed result comes from here
(see `RankingConfig.constants`), so the numeric guardrail can tell a configured
parameter ("a 200-day SMA") from an invented statistic.

The strategy is the month-end ETF ranking from `download_prices.ipynb`
("Rank on the moving average instead of the close"): at each month end, rank a
fixed ETF universe by the % change of a signal (the close, or a simple moving
average of it) over a trailing calendar-day lookback, and hold the leaders to
the next month end.
"""

from dataclasses import asdict, dataclass, field

UNIVERSE = ("SPY", "QQQ", "TLT", "IEF", "GLD", "USO", "JNK")
BENCHMARKS = ("SPY", "QQQ")         # buy & hold comparisons; SPY is the reference for "vs SPY"
RATE_TICKER = "^IRX"                # 13-week T-bill yield, % annualized: the risk-free rate for Sharpe
ALLOWED_TICKERS = (*UNIVERSE, RATE_TICKER)

TRADING_DAYS = 252

# Analysis windows: label -> calendar months back from the last date (None = the whole scored period)
WINDOWS = {"1Y": 12, "3Y": 36, "5Y": 60, "SI": None}
ANNUALIZE_FROM_MONTHS = 12          # windows shorter than this report total return only

# Portfolio construction by name. A tuple is the long-only weight by rank (top 1, top 2, ...).
# LONG_SHORT holds the Top 3 mix and shorts every other ETF with a negative trailing change.
TOP1, TOP3, LONG_SHORT = "Top 1", "Top 3 mix", "Long top 3, short negatives"
PORTFOLIOS = {TOP1: (1.0,), TOP3: (0.5, 0.3, 0.2), LONG_SHORT: (0.5, 0.3, 0.2)}


@dataclass(frozen=True)
class RankingConfig:
    """Parameters of the month-end ranking strategy and of the two research rounds.

    Attributes:
        universe: ETFs ranked each month end.
        start: first date of price history (the notebook's START).
        signals: SMA windows in trading days; 0 means the raw close (the unsmoothed baseline).
        lookbacks: calendar days over which each signal's % change is ranked.
        portfolios: portfolio names run in round 1 (keys of `PORTFOLIOS`).
        top_n: how many strategies the Portfolio Manager keeps.
        n_proposals: how many new parameter sets the Portfolio Manager proposes for round 2.
        sma_range, lookback_range: inclusive bounds on round-2 proposals.
        blend_weight: strategy share in the SPY + strategy blend used for the portfolio-fit analysis.
        cost_bps: modeled trading cost (0: the notebook has none, and the deck discloses it).
    """
    universe: tuple = UNIVERSE
    start: str = "2015-01-01"
    signals: tuple = (0, 20, 50, 200)
    lookbacks: tuple = (15, 30, 60, 90, 120, 150, 180)
    portfolios: tuple = (TOP1, TOP3, LONG_SHORT)
    top_n: int = 5
    n_proposals: int = 5
    sma_range: tuple = (5, 250)
    lookback_range: tuple = (10, 365)
    blend_weight: float = 0.2
    cost_bps: float = 0.0

    @property
    def grid_size(self):
        """Number of round-1 strategies (portfolio x signal x lookback)."""
        return len(self.portfolios) * len(self.signals) * len(self.lookbacks)

    def constants(self):
        """Parameter values agents may legitimately mention in prose.

        Returns:
            A set of numbers: SMA windows, lookbacks, rank weights as whole percents,
            universe and grid sizes, the round sizes, the blend split and the start year.
        """
        weights = {round(w * 100) for ws in PORTFOLIOS.values() for w in ws}
        blend = {round(self.blend_weight * 100), round((1 - self.blend_weight) * 100)}
        return {*self.signals, *self.lookbacks, *self.sma_range, *self.lookback_range, *weights, *blend,
                len(self.universe), self.grid_size, self.grid_size + self.n_proposals, self.top_n,
                self.n_proposals, len(self.portfolios), len(self.signals), int(self.start[:4]), 2, 100}

    def to_dict(self):
        """Plain-dict copy for manifests and JSON artifacts."""
        return asdict(self)


@dataclass
class PipelineConfig:
    """Run-level settings: the strategy, the model and the run's hard limits."""
    ranking: RankingConfig = field(default_factory=RankingConfig)
    model: str = "claude-opus-5-5"
    max_turns_per_agent: int = 20
    token_budget: int = 4_000_000          # hard cap on input + output tokens per run
    offline: bool = False                  # use cached prices instead of Yahoo Finance
