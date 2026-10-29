"""Agent loop on the Claude Messages API, with tracing, a token budget and cost accounting.

Same core loop as the other projects: call Claude, run requested tools
(concurrently), append all results in one message, repeat until a text reply.
The history is append-only. Bad arguments and domain errors come back to the
model as `is_error` tool results so it can correct itself.

Two additions for this project:

- **Hooks.** Every tool call passes through the run's pre-tool hooks (which can
  deny it, see `strategy.hooks`) and post-tool hooks.
- **Cost per tool.** Each model call's usage is attributed to the content that
  caused it, so the manifest can report tokens and dollars per tool:
  - input-side tokens (fresh input, cache writes, cache reads) are split across
    the history segments the call re-read, by owner, in proportion to their
    characters. Owners are "(system & tool definitions)", "(task)", "(agent
    text)" and each tool, which owns its tool_use requests and its results;
  - output tokens are split across the call's text and tool_use blocks the same way;
  - each share is priced at that call's actual rates, so the per-tool costs sum
    exactly to the run's total cost.
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
        self.by_tool = {}          # owner -> {"input_tokens", "output_tokens", "cost_usd"} (floats)
        self.by_agent_tool = {}    # agent -> owner -> same

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

    def attribute(self, agent, history, output, usage):
        """Attribute one model call's usage to the owners of its input and output content.

        Args:
            agent: the calling agent's name.
            history: ``[(owner, chars), ...]`` for everything sent in the request.
            output: ``[(owner, chars), ...]`` for the response blocks.
            usage: the call's usage dict from `add_usage`.

        Side effects:
            Adds proportional token and dollar shares to `by_tool` and `by_agent_tool`.
        """
        in_tokens = usage["input"] + usage["cache_write"] + usage["cache_read"]
        in_cost = sum(usage[k] * PRICES[k] for k in ("input", "cache_write", "cache_read")) / 1_000_000
        out_tokens, out_cost = usage["output"], usage["output"] * PRICES["output"] / 1_000_000
        with self._lock:
            for parts, tokens, cost, kind in ((history, in_tokens, in_cost, "input_tokens"),
                                              (output, out_tokens, out_cost, "output_tokens")):
                for owner, share in _shares(parts).items():
                    for table in (self.by_tool, self.by_agent_tool.setdefault(agent, {})):
                        row = table.setdefault(owner, {"input_tokens": 0.0, "output_tokens": 0.0, "cost_usd": 0.0})
                        row[kind] += tokens * share
                        row["cost_usd"] += cost * share

    def tool_report(self):
        """Per-owner tokens and cost, rounded for the manifest, most expensive first."""
        rows = sorted(self.by_tool.items(), key=lambda kv: -kv[1]["cost_usd"])
        return {owner: {"input_tokens": round(r["input_tokens"]), "output_tokens": round(r["output_tokens"]),
                        "cost_usd": round(r["cost_usd"], 4)} for owner, r in rows}

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


SYSTEM_OWNER, TASK_OWNER, TEXT_OWNER = "(system & tool definitions)", "(task)", "(agent text)"


def _shares(parts):
    """Fractions of the total characters owned by each owner (all to "(agent text)" if empty)."""
    total = sum(chars for _, chars in parts)
    if total <= 0:
        return {TEXT_OWNER: 1.0}
    out = {}
    for owner, chars in parts:
        out[owner] = out.get(owner, 0.0) + chars / total
    return out


def _output_parts(content):
    """``[(owner, chars)]`` for a response: text and thinking belong to the agent, tool_use to its tool."""
    parts = []
    for b in content:
        if b.type == "tool_use":
            parts.append((b.name, len(b.name) + len(json.dumps(b.input, default=str))))
        elif b.type == "text":
            parts.append((TEXT_OWNER, len(b.text)))
        elif b.type == "thinking":
            parts.append((TEXT_OWNER, len(getattr(b, "thinking", "") or "")))
    return parts


class Agent:
    def __init__(self, client, name, system, tools, trace, effort="medium", max_turns=20,
                 token_budget=None, model=MODEL, hooks=None):
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
        self.hooks = hooks

    def run(self, task):
        """Run the agent on one task until it replies in text. Returns the reply."""
        messages = [{"role": "user", "content": task}]
        # Who owns each piece of the growing history, for per-tool cost attribution.
        ledger = [(SYSTEM_OWNER, len(self.system) + len(json.dumps(self.tool_params))), (TASK_OWNER, len(task))]
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
            output = _output_parts(response.content)
            self.trace.attribute(self.name, ledger, output, usage)
            ledger += output
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
            ledger += [(b.name, len(r["content"])) for b, r in zip(tool_uses, results)]
            messages.append({"role": "user", "content": results})
        raise AgentError(f"{self.name} did not finish within {self.max_turns} turns.")

    def _execute(self, block):
        tool = self.tools.get(block.name)
        t0 = time.perf_counter()
        ok = False
        try:
            denied = self.hooks.before(self.name, block.name, block.input) if self.hooks else None
            if denied:
                hook, reason = denied
                self.trace.log(agent=self.name, type="hook_denied", tool=block.name, hook=hook, reason=reason)
                raise ToolError(f"Denied by the {hook} hook: {reason}")
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
        if self.hooks:
            self.hooks.after(self.name, block.name, block.input, ok, content)
        self.trace.log(agent=self.name, type="tool", tool=block.name, input=block.input, ok=ok,
                       latency_s=round(time.perf_counter() - t0, 3),
                       error=None if ok else content[:500],
                       # The exact text returned to the model, so evals/token_profile.py can count its tokens.
                       result=content, result_chars=len(content))
        result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
        if not ok:
            result["is_error"] = True
        return result


def make_client():
    return anthropic.Anthropic()
