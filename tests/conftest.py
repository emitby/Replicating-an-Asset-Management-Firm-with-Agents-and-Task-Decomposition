"""Shared fixtures: a project-local work folder, synthetic prices, and scripted Claude clients."""

import secrets
import threading
from types import SimpleNamespace as NS

import pytest

from strategy.paths import PROJECT_DIR

# Test files stay inside the project (gitignored) and are never deleted (CLAUDE.md guardrail).
TEST_ROOT = PROJECT_DIR / ".pytest_tmp"


@pytest.fixture
def workdir():
    """A fresh folder under .pytest_tmp/ for one test."""
    d = TEST_ROOT / secrets.token_hex(6)
    d.mkdir(parents=True)
    return d


@pytest.fixture(scope="session")
def prices():
    """Cleaned synthetic prices for the seven-ETF universe plus ^IRX (no network)."""
    from strategy.data import clean, synthetic_prices
    return clean(synthetic_prices())


# ---- scripted Claude clients ----------------------------------------------------

def text(t):
    """A text content block."""
    return NS(type="text", text=t)


def tool_use(id_, name, **input_):
    """A tool_use content block."""
    return NS(type="tool_use", id=id_, name=name, input=input_)


def response(*content, stop="end_turn"):
    """A Messages API response with fixed usage (100 input, 20 output tokens)."""
    usage = NS(input_tokens=100, output_tokens=20, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return NS(content=list(content), stop_reason=stop, usage=usage)


class FakeClaude:
    """Returns scripted responses in order and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.responses.pop(0)
        return item() if callable(item) else item


class ScriptedClaude:
    """Routes each request to a per-agent script, chosen by the agent's system prompt ("You are the X").

    Scripts are lists of responses or zero-argument callables (evaluated at request time, so a
    script can use results computed earlier in the run). Thread-safe: the Team Agent runs in parallel.
    """

    def __init__(self, scripts):
        self.scripts = {name: list(items) for name, items in scripts.items()}
        self.requests = []
        self._lock = threading.Lock()
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        name = next(n for n in self.scripts if f"You are the {n}" in kwargs["system"])
        with self._lock:
            self.requests.append({"agent": name, **kwargs, "messages": list(kwargs["messages"])})
            item = self.scripts[name].pop(0)
        return item() if callable(item) else item


@pytest.fixture(scope="session")
def offline_run(prices):
    """One complete scripted pipeline run (all six agents, real harness and PDF), shared by tests."""
    from pipeline_script import run_offline_pipeline
    run_dir = TEST_ROOT / f"pipeline-{secrets.token_hex(4)}"
    run_dir.mkdir(parents=True)
    return run_offline_pipeline(run_dir, prices)
