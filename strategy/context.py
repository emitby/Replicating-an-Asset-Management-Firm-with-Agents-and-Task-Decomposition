"""State shared by the harness and the agents' tools during one run."""

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from strategy.config import PipelineConfig
from strategy.guardrails import NumberIndex
from strategy.paths import confine, read_json


@dataclass
class RunContext:
    run_dir: Path
    cfg: PipelineConfig
    trace: object
    client: object = None
    raw: pd.DataFrame = None            # downloaded prices
    data_report: dict = None
    prices: pd.DataFrame = None         # cleaned dataset
    wf: dict = None                     # walk-forward result
    returns: pd.DataFrame = None        # daily returns: Strategy, SPY, 60/40, MA*, w_spy, rf
    candidates: dict = None             # in-sample single-MA stats
    backtest: dict = None               # saved backtest summary
    analytics: dict = None
    team: dict = None
    slides: list = field(default_factory=list)   # [{"type": "slide"|"metrics_table"|..., ...}]
    charts: dict = field(default_factory=dict)   # kind -> png path
    notes: dict = field(default_factory=dict)    # agent -> final reply
    calls: dict = field(default_factory=dict)    # tool -> list of inputs (for preconditions)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def path(self, *parts):
        return confine(Path(self.run_dir, *parts))

    def record(self, tool, **inputs):
        with self.lock:
            self.calls.setdefault(tool, []).append(inputs)

    def number_index(self):
        """Every number agents may cite: computed results plus configured constants."""
        data_facts = None
        if self.data_report:
            data_facts = {"rows": self.data_report.get("rows")}
        return NumberIndex(self.analytics or {}, self.backtest or {}, data_facts or {},
                           constants=self.cfg.strategy.constants())

    def load_artifacts(self, src_dir):
        """Load saved artifacts from an earlier run (for re-running a single stage)."""
        src = confine(src_dir)
        if (src / "prices.csv").exists():
            self.prices = pd.read_csv(src / "prices.csv", index_col=0, parse_dates=True)
        if (src / "data_report.json").exists():
            self.data_report = read_json(src / "data_report.json")
        if (src / "returns.csv").exists():
            self.returns = pd.read_csv(src / "returns.csv", index_col=0, parse_dates=True)
        if (src / "backtest.json").exists():
            self.backtest = read_json(src / "backtest.json")
            self.candidates = self.backtest.get("candidates_in_sample")
        if (src / "analytics.json").exists():
            self.analytics = read_json(src / "analytics.json")
        if (src / "team.json").exists():
            self.team = read_json(src / "team.json")
