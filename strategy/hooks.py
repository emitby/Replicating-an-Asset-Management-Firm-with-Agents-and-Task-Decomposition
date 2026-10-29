"""Tool-use hooks for the agent runtime (pre- and post-tool-use, like Claude Code's hooks).

Every tool call an agent makes passes through `Hooks.before` before its handler
runs and `Hooks.after` once it returns. A pre-tool hook can **deny** the call:
the handler never runs, the model receives the denial as an ``is_error`` tool
result (so it can adjust), and the trace records a ``hook_denied`` event.

Built-in pre-tool hooks (CLAUDE.md guardrails, enforced at the agent boundary):

- `forbid_delete`: no tool that deletes anything may run, and no tool input may
  carry a delete command (``rm``, ``del``, ``Remove-Item``, ``os.remove``,
  ``shutil.rmtree``, ``.unlink()``...).
- `confine_paths`: any tool input that looks like a filesystem path must resolve
  inside the project directory (absolute paths elsewhere, ``~`` and ``..``
  traversal out of the project are denied).

Built-in post-tool hook:

- `count_calls`: per-agent, per-tool call counts and failures, reported in the
  manifest next to the per-tool cost.

The runtime hooks guard what agents *ask for*. The process-level audit hook in
`strategy.sandbox` guards what the Python process actually *does*, and the
Claude Code hook in ``.claude/hooks/guard.py`` guards developer sessions.
"""

import re
import threading
from dataclasses import dataclass, field
from typing import Callable

from strategy.paths import ConfinementError, confine

# Tool names that would delete something. No tool in this project matches; the hook makes sure
# none can be added and used by accident.
DELETE_TOOL_RE = re.compile(r"(delete|remove|unlink|rmtree|rmdir|erase|purge|wipe)", re.IGNORECASE)
# Delete commands inside an input value (shell or Python). Plain prose ("the PM removed T1-...")
# doesn't match: only command syntax does.
DELETE_COMMAND_RE = re.compile(
    r"(^|[;&|`$(]\s*|\n\s*)(rm|del|rmdir|rd|erase|unlink)\s+[-/\w.~\\]"
    r"|Remove-Item|\bos\.(remove|unlink|rmdir|removedirs)\s*\(|\bshutil\.rmtree\s*\(|\.unlink\s*\(|\.rmdir\s*\("
    r"|\bgit\s+(rm|clean)\b",
    re.IGNORECASE)
# A value that looks like a filesystem path: absolute (POSIX, home, Windows drive or UNC) or one that
# climbs with "..". Prose like "50/30/20" or "SPY/QQQ" doesn't match.
PATH_LIKE_RE = re.compile(r"^\s*(/|~|[A-Za-z]:[\\/]|\\\\)|(^|[\\/])\.\.([\\/]|$)")


@dataclass
class Hooks:
    """Ordered lists of pre- and post-tool-use hooks.

    Attributes:
        pre: callables ``(agent, tool, tool_input) -> str | None``. A string is a denial
            reason; the first denial wins and the tool does not run.
        post: callables ``(agent, tool, tool_input, ok, content) -> None``, run after every call
            (including denied and failed ones) for accounting and auditing.
    """
    pre: list = field(default_factory=list)
    post: list = field(default_factory=list)

    def before(self, agent, tool, tool_input):
        """Run the pre-tool hooks in order.

        Returns:
            ``(hook_name, reason)`` for the first denial, or ``None`` if every hook allows the call.
        """
        for hook in self.pre:
            reason = hook(agent, tool, tool_input)
            if reason:
                return getattr(hook, "__name__", "hook"), reason
        return None

    def after(self, agent, tool, tool_input, ok, content):
        """Run every post-tool hook (their return values are ignored)."""
        for hook in self.post:
            hook(agent, tool, tool_input, ok, content)


def _strings(obj):
    """Every string inside a (nested) tool input."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def forbid_delete(agent, tool, tool_input):
    """Deny any tool whose name implies deletion, or whose input carries a delete command.

    Returns:
        A denial reason, or ``None`` to allow.
    """
    if DELETE_TOOL_RE.search(tool):
        return f"Tool {tool!r} would delete data. Deleting files is forbidden in this project."
    for s in _strings(tool_input):
        if DELETE_COMMAND_RE.search(s):
            return "The input contains a delete command. Deleting files is forbidden in this project."
    return None


def confine_paths(agent, tool, tool_input):
    """Deny any path-like input that resolves outside the project directory.

    Returns:
        A denial reason, or ``None`` to allow.
    """
    for s in _strings(tool_input):
        if len(s) > 400 or "\n" in s or not PATH_LIKE_RE.search(s):
            continue  # prose, not a path
        path = s.strip()
        denial = f"Path {path[:80]!r} is outside the project directory. Access is forbidden."
        if path.startswith("~"):
            return denial  # a home directory is never inside the project
        try:
            confine(path)
        except (ConfinementError, OSError, ValueError):
            return denial
    return None


class CallCounter:
    """Post-tool hook that counts calls and failures per agent and tool (thread-safe)."""

    __name__ = "count_calls"

    def __init__(self):
        self.counts = {}
        self._lock = threading.Lock()

    def __call__(self, agent, tool, tool_input, ok, content):
        with self._lock:
            c = self.counts.setdefault(agent, {}).setdefault(tool, {"calls": 0, "errors": 0})
            c["calls"] += 1
            c["errors"] += 0 if ok else 1


def default_hooks():
    """The hooks every pipeline agent runs with: `forbid_delete`, `confine_paths` and a call counter."""
    return Hooks(pre=[forbid_delete, confine_paths], post=[CallCounter()])


# Code-owned descriptions for the PDF's harness page (so the deck can't drift from the code).
HOOK_DESCRIPTIONS = {
    "forbid_delete (pre-tool)": "Denies any tool whose name implies deletion and any input carrying a delete "
                                "command (rm, del, Remove-Item, os.remove, shutil.rmtree, .unlink()).",
    "confine_paths (pre-tool)": "Denies any path-like input that resolves outside the project folder "
                                "(absolute paths elsewhere, ~, or .. traversal).",
    "count_calls (post-tool)": "Counts calls and failures per agent and tool for the run manifest.",
    "audit hook (process)": "A Python audit hook blocks file deletion, writes outside the project and reads "
                            "outside the project and the Python installation, whatever code asks for it.",
    "guard.py (Claude Code)": "A PreToolUse hook stops developer sessions from deleting files or reading, "
                              "writing or searching outside the project.",
}
