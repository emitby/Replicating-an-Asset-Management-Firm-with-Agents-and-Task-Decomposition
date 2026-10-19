"""Agent loop on the Claude Messages API, with tracing, a token budget and cost accounting.

Same core loop as the other projects: call Claude, run requested tools
(concurrently), append all results in one message, repeat until a text reply.
The history is append-only. Bad arguments and domain errors come back to the
model as `is_error` tool results so it can correct itself.
"""

import inspect
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import anthropic

from strategy.paths import confine

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000
# USD per million tokens for claude-opus-5-5: input, output, cache write (1.25x), cache read
PRICES = {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20}
REFUSAL_REPLY = "The model declined this request."


class AgentError(RuntimeError):
    pass


class BudgetExceeded(AgentError):
    pass


class ToolError(ValueError):
    """A domain or validation error that the model should see and fix."""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Any]

    def to_param(self):
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required),
            "additionalProperties": False}


class Trace:
    """Append-only JSONL log of every model call and tool call, plus usage totals."""

    def __init__(self, path):
        self.path = confine(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.usage = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        self.by_agent = {}

    def log(self, **event):
        event["ts"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = json.dumps(event, default=str)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def add_usage(self, agent, usage):
        u = {"input": usage.input_tokens or 0, "output": usage.output_tokens or 0,
             "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
             "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0}
        with self._lock:
            for k, v in u.items():
                self.usage[k] += v
                self.by_agent.setdefault(agent, dict.fromkeys(self.usage, 0))[k] += v
        return u

    @property
    def total_tokens(self):
        return sum(self.usage.values())

    def cost_usd(self, usage=None):
        u = usage or self.usage
        return round(sum(u[k] * PRICES[k] for k in PRICES) / 1_000_000, 4)

    def events(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]


class Agent:
    def __init__(self, client, name, system, tools, trace, effort="medium", max_turns=20,
                 token_budget=None, model=MODEL):
        self.client = client
        self.name = name
        self.system = system
        self.tools = {t.name: t for t in tools}
        self.tool_params = [t.to_param() for t in tools]
        self.trace = trace
        self.effort = effort
        self.max_turns = max_turns
        self.token_budget = token_budget
        self.model = model

    def run(self, task):
        """Run the agent on one task until it replies in text. Returns the reply."""
        messages = [{"role": "user", "content": task}]
        self.trace.log(agent=self.name, type="start", task=task)
        for turn in range(self.max_turns):
            if self.token_budget and self.trace.total_tokens > self.token_budget:
                raise BudgetExceeded(f"Run token budget of {self.token_budget:,} exceeded.")
            t0 = time.perf_counter()
            response = self.client.beta.messages.create(
                model=self.model, max_tokens=MAX_TOKENS, system=self.system, tools=self.tool_params,
                messages=messages, output_config={"effort": self.effort},
                cache_control={"type": "ephemeral"}, betas=[FALLBACK_BETA], fallbacks="default",
            )
            usage = self.trace.add_usage(self.name, response.usage)
            self.trace.log(agent=self.name, type="model", turn=turn, stop_reason=response.stop_reason,
                           latency_s=round(time.perf_counter() - t0, 2), usage=usage)
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                self.trace.log(agent=self.name, type="refusal")
                return REFUSAL_REPLY
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                reply = "\n".join(b.text for b in response.content if b.type == "text").strip()
                self.trace.log(agent=self.name, type="finish", reply=reply)
                return reply
            with ThreadPoolExecutor(max_workers=len(tool_uses)) as pool:
                results = list(pool.map(self._execute, tool_uses))
            messages.append({"role": "user", "content": results})
        raise AgentError(f"{self.name} did not finish within {self.max_turns} turns.")

    def _execute(self, block):
        tool = self.tools.get(block.name)
        t0 = time.perf_counter()
        ok = False
        try:
            if tool is None:
                raise ToolError(f"Unknown tool {block.name!r}. Available: {sorted(self.tools)}.")
            if not isinstance(block.input, dict):
                raise ToolError("Tool input must be a JSON object.")
            try:
                inspect.signature(tool.handler).bind(**block.input)
            except TypeError as exc:
                raise ToolError(f"Invalid arguments for {block.name}: {exc}") from None
            out = tool.handler(**block.input)
            content = out if isinstance(out, str) else json.dumps(out, default=str)
            ok = True
        except ToolError as exc:
            content = str(exc)
        except (ValueError, KeyError) as exc:
            content = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # unexpected: log it, keep the run alive
            content = f"Internal error in {block.name}: {type(exc).__name__}"
            self.trace.log(agent=self.name, type="tool_crash", tool=block.name, error=repr(exc))
        self.trace.log(agent=self.name, type="tool", tool=block.name, input=block.input, ok=ok,
                       latency_s=round(time.perf_counter() - t0, 3),
                       error=None if ok else content[:500])
        result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
        if not ok:
            result["is_error"] = True
        return result


def make_client():
    return anthropic.Anthropic()
