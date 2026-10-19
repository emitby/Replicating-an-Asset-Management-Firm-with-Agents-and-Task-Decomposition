import secrets
from types import SimpleNamespace as NS

import pytest

from strategy.paths import PROJECT_DIR

# Test files stay inside the project (gitignored) and are never deleted (CLAUDE.md guardrail).
TEST_ROOT = PROJECT_DIR / ".pytest_tmp"


@pytest.fixture
def workdir():
    d = TEST_ROOT / secrets.token_hex(6)
    d.mkdir(parents=True)
    return d


@pytest.fixture(scope="session")
def prices():
    from strategy.data import clean, synthetic_prices
    return clean(synthetic_prices())


@pytest.fixture(scope="session")
def backtest_result(prices):
    from strategy.backtest import run_all
    from strategy.config import StrategyConfig
    return run_all(prices, StrategyConfig())


# ---- scripted Claude client ----------------------------------------------------

def text(t):
    return NS(type="text", text=t)


def tool_use(id_, name, **input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def response(*content, stop="end_turn"):
    usage = NS(input_tokens=100, output_tokens=20, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return NS(content=list(content), stop_reason=stop, usage=usage)


class FakeClaude:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)
