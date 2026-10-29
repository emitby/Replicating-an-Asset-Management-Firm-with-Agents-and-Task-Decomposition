"""State shared by the harness and the agents' tools during one run.

`RunContext` is the only mutable state in a run. Agents never touch it
directly: their tools read and write it, the harness validates it after each
stage, and `load_artifacts` rebuilds it from a finished run so a single stage
(or just the PDF) can be redone without re-running the agents before it.
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from strategy.config import PipelineConfig
from strategy.guardrails import NumberIndex
from strategy.paths import confine, read_json


@dataclass
class RunContext:
    """Everything one pipeline run produces, plus its config, trace and client.

    Attributes:
        run_dir: the run's folder under ``runs/``.
        cfg: pipeline configuration.
        trace: the run's `Trace` (JSONL log, token and cost totals).
        client: the Anthropic client (or a scripted fake in tests).
        hooks: pre/post tool-use hooks applied to every agent (`strategy.hooks.Hooks`).
        raw, data_report, prices: fetched data, its quality report and the cleaned dataset.
        returns: daily returns of every strategy run so far (columns are strategy ids) plus SPY, QQQ and rf.
        specs: strategy id -> `ranking.StrategySpec`.
        picks: strategy id -> month-end picks (not saved; recomputed on demand after a reload).
        facts: other computed values a tool has shown an agent (e.g. how often each ETF led), so
            they are citable; saved in research.json.
        scores: risk/return table over the common window (rows: strategy ids, SPY, QQQ).
        window_start: first scored date (the round-1 common start).
        research: round -> {"ids", "findings", "message"} saved by the Research Agent.
        pm: the Portfolio Manager's decisions: top5, proposals, final, meeting.
        dialogue: ordered messages between the agents (from, to, round, text, items).
        analytics, team: saved outputs of the Analytics and Team Agents.
        slides, charts: the Presentation Agent's slides and rendered chart paths.
        notes: agent name -> final reply.
        calls: tool name -> list of inputs (used for preconditions and evals).
    """
    run_dir: Path
    cfg: PipelineConfig
    trace: object
    client: object = None
    hooks: object = None
    raw: pd.DataFrame = None
    data_report: dict = None
    prices: pd.DataFrame = None
    returns: pd.DataFrame = None
    specs: dict = field(default_factory=dict)
    picks: dict = field(default_factory=dict)
    facts: dict = field(default_factory=dict)
    scores: pd.DataFrame = None
    window_start: pd.Timestamp = None
    research: dict = field(default_factory=dict)
    pm: dict = field(default_factory=dict)
    dialogue: list = field(default_factory=list)
    analytics: dict = None
    team: dict = None
    slides: list = field(default_factory=list)
    charts: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def path(self, *parts):
        """A path inside the run folder (confined to the project)."""
        return confine(Path(self.run_dir, *parts))

    def record(self, tool, **inputs):
        """Remember that `tool` was called with `inputs` (thread-safe)."""
        with self.lock:
            self.calls.setdefault(tool, []).append(inputs)

    def say(self, sender, to, round_, text, items=None):
        """Append one message to the agent dialogue (rendered in the PDF's decision log).

        Args:
            sender, to: agent names.
            round_: research round (1 or 2), or 0 for the final decision.
            text: the agent-written message (already guardrail-checked by the calling tool).
            items: optional structured content (picks, proposals, decisions).
        """
        with self.lock:
            self.dialogue.append({"from": sender, "to": to, "round": round_, "text": text, "items": items or []})

    def number_index(self, extra=()):
        """Every number agents may cite: computed results plus configured constants.

        Sources are the scores table (full precision), other computed facts shown to agents,
        the analytics, the PM's computed replacement figures, the parameters of the PM's
        proposals, and the dataset row count. The guardrail accepts any of these at the
        rounding the text uses.

        Args:
            extra: additional citable constants (e.g. the parameters of proposals being validated).
        """
        scores = self.scores.to_dict() if self.scores is not None else {}
        data_facts = {"rows": (self.data_report or {}).get("cleaned_rows")}
        replacements = (self.pm.get("final") or {}).get("replacements", [])
        params = {v for p in self.pm.get("proposals", []) for v in (p["sma"], p["lookback_days"])}
        return NumberIndex(scores, self.facts, self.analytics or {}, replacements, data_facts,
                           constants=self.cfg.ranking.constants() | params | set(extra))

    def load_artifacts(self, src_dir):
        """Load saved artifacts from an earlier run (to re-run a later stage or rebuild the PDF).

        Args:
            src_dir: a finished run folder inside the project.

        Side effects:
            Populates prices, returns, specs, scores, window_start, research, pm, dialogue,
            analytics and team from whichever files exist.
        """
        from strategy.ranking import StrategySpec
        src = confine(src_dir)
        if (src / "prices.csv").exists():
            self.prices = pd.read_csv(src / "prices.csv", index_col=0, parse_dates=True)
        if (src / "data_report.json").exists():
            self.data_report = read_json(src / "data_report.json")
        if (src / "strategy_returns.csv").exists():
            self.returns = pd.read_csv(src / "strategy_returns.csv", index_col=0, parse_dates=True)
        if (src / "research.json").exists():
            saved = read_json(src / "research.json")
            self.specs = {sid: StrategySpec(d["portfolio"], d["sma"], d["lookback_days"])
                          for sid, d in saved["strategies"].items()}
            self.scores = pd.DataFrame(saved["scores"]).T
            self.window_start = pd.Timestamp(saved["window_start"])
            self.research = {int(k): v for k, v in saved["rounds"].items()}
            self.facts = saved.get("facts", {})
        if (src / "pm.json").exists():
            self.pm = read_json(src / "pm.json")
        if (src / "dialogue.json").exists():
            self.dialogue = read_json(src / "dialogue.json")
        if (src / "analytics.json").exists():
            self.analytics = read_json(src / "analytics.json")
        if (src / "team.json").exists():
            self.team = read_json(src / "team.json")
