"""Tests for the runtime tool hooks, the process sandbox, the Claude Code hook, and per-tool cost accounting."""

import importlib.util
import json
import subprocess
import sys

import pytest

from conftest import FakeClaude, response, text, tool_use
from strategy.agents.runtime import Agent, Tool, Trace, schema
from strategy.hooks import CallCounter, Hooks, confine_paths, default_hooks, forbid_delete
from strategy.paths import CACHE_DIR, PROJECT_DIR
from strategy.sandbox import check_event


# ------------------------------------------------------------------ runtime hooks

@pytest.mark.parametrize("tool, tool_input", [
    ("delete_file", {}), ("purge_cache", {}),
    ("run", {"cmd": "rm -rf data"}), ("run", {"cmd": "echo x; del runs\\a.txt"}),
    ("run", {"code": "import os; os.remove('a')"}), ("run", {"code": "Path('a').unlink()"}),
    ("run", {"cmd": "git clean -fdx"}),
])
def test_forbid_delete_blocks(tool, tool_input):
    assert forbid_delete("a", tool, tool_input)


@pytest.mark.parametrize("tool_input", [
    {"message": "The PM removed one strategy."}, {"title": "Remove the weakest"},
    {"bullets": ["No history is deleted; the firm's rm-free design."]},
])
def test_forbid_delete_allows_prose(tool_input):
    assert forbid_delete("a", "finalize", tool_input) is None


@pytest.mark.parametrize("value, blocked", [
    ("../x.txt", True), ("runs/../../x", True), ("C:/Windows/win.ini", True), ("~/x", True), ("/etc/passwd", True),
    ("runs/x/notes.md", False), (str(PROJECT_DIR / "runs" / "a.png"), False), ("50/30/20", False), ("SPY/QQQ", False),
])
def test_confine_paths(value, blocked):
    assert bool(confine_paths("a", "save", {"nested": [{"path": value}]})) == blocked


def test_denied_tool_never_runs_and_is_traced(workdir):
    ran = []
    tools = [Tool("save", "Save.", schema({"path": {"type": "string"}}, ["path"]), lambda path: ran.append(path) or "ok")]
    client = FakeClaude(response(tool_use("1", "save", path="../../escape.txt"), stop="tool_use"), response(text("ok")))
    trace = Trace(workdir / "trace.jsonl")
    counter = CallCounter()
    Agent(client, "A", "sys", tools, trace, hooks=Hooks(pre=[confine_paths], post=[counter])).run("go")
    assert ran == []
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "confine_paths" in result["content"]
    assert [e["hook"] for e in trace.events() if e["type"] == "hook_denied"] == ["confine_paths"]
    assert counter.counts == {"A": {"save": {"calls": 1, "errors": 1}}}


def test_default_hooks_names():
    hooks = default_hooks()
    assert [h.__name__ for h in hooks.pre] == ["forbid_delete", "confine_paths"]
    assert [getattr(h, "__name__") for h in hooks.post] == ["count_calls"]


# ------------------------------------------------------------------ process sandbox

@pytest.mark.parametrize("event, args, blocked", [
    ("os.remove", (str(PROJECT_DIR / "README.md"), None), True),
    ("shutil.rmtree", (str(PROJECT_DIR / "runs"),), True),
    ("os.rmdir", (str(PROJECT_DIR / "runs"), None), True),
    ("open", (str(PROJECT_DIR.parent / "x.txt"), "w", 0), True),
    ("open", (str(PROJECT_DIR.parent / "x.txt"), "r", 0), True),
    ("os.replace", (str(PROJECT_DIR / "a"), str(PROJECT_DIR.parent / "b"), None, None), True),
    ("os.mkdir", (str(PROJECT_DIR.parent / "d"), 0o777, None), True),
    ("open", (str(PROJECT_DIR / "runs" / "a.txt"), "w", 0), False),
    ("open", (str(PROJECT_DIR / "README.md"), "r", 0), False),
    ("open", (sys.base_prefix + "/Lib/json/__init__.py", "rb", 0), False),
    ("os.remove", (str(CACHE_DIR / "matplotlib" / "fontlist.lock"), None), False),
    ("open", (3, "r", 0), False),
])
def test_sandbox_rules(event, args, blocked):
    assert (check_event(event, args) is not None) == blocked


def test_sandbox_installed_in_a_real_process():
    """The audit hook can't be removed once installed, so exercise it in a child process."""
    code = (
        "from pathlib import Path\n"
        "from strategy import sandbox\n"
        "from strategy.paths import PROJECT_DIR\n"
        "sandbox.install()\n"
        "import pandas\n"
        "out = []\n"
        "for name, fn in [('unlink', lambda: (PROJECT_DIR / 'README.md').unlink()),\n"
        "                 ('write_outside', lambda: (PROJECT_DIR.parent / 'sbx.txt').write_text('x')),\n"
        "                 ('read_outside', lambda: (PROJECT_DIR.parent / 'sbx.txt').read_text())]:\n"
        "    try:\n"
        "        fn(); out.append(name + ':allowed')\n"
        "    except sandbox.SandboxViolation:\n"
        "        out.append(name + ':blocked')\n"
        "print(','.join(out))\n")
    proc = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=120)
    assert proc.stdout.strip() == "unlink:blocked,write_outside:blocked,read_outside:blocked", proc.stderr
    assert (PROJECT_DIR / "README.md").exists()


# ------------------------------------------------------------------ Claude Code hook

def _guard():
    spec = importlib.util.spec_from_file_location("guard", PROJECT_DIR / ".claude" / "hooks" / "guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("tool, tool_input, blocked", [
    ("Bash", {"command": "rm -f runs/a"}, True),
    ("Bash", {"command": "ls && rmdir runs/x"}, True),
    ("Bash", {"command": "powershell Remove-Item x"}, True),
    ("Bash", {"command": "git rm README.md"}, True),
    ("Bash", {"command": "cat /c/Windows/win.ini"}, True),
    ("Bash", {"command": "cp README.md ../copy.md"}, True),
    ("Read", {"file_path": "C:/Windows/win.ini"}, True),
    ("Edit", {"file_path": str(PROJECT_DIR.parent / "x.py")}, True),
    ("Grep", {"pattern": "x", "path": "C:/Users"}, True),
    ("Bash", {"command": "grep -n rm strategy/hooks.py"}, False),
    ("Bash", {"command": "python -m pytest -q > /dev/null"}, False),
    ("Read", {"file_path": str(PROJECT_DIR / "README.md")}, False),
    ("Write", {"file_path": "tasks/todo.md"}, False),
])
def test_claude_code_guard(tool, tool_input, blocked):
    assert (_guard().check(tool, tool_input) is not None) == blocked


def test_claude_code_guard_exit_codes():
    """End to end, as Claude Code calls it: JSON on stdin, exit 2 blocks with a reason on stderr."""
    guard = PROJECT_DIR / ".claude" / "hooks" / "guard.py"
    deny = subprocess.run([sys.executable, str(guard)], input=json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf runs"}}), capture_output=True, text=True, timeout=60)
    allow = subprocess.run([sys.executable, str(guard)], input=json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls runs"}}), capture_output=True, text=True, timeout=60)
    assert deny.returncode == 2 and "forbidden" in deny.stderr
    assert allow.returncode == 0


def test_settings_register_the_guard():
    settings = json.loads((PROJECT_DIR / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entry = settings["hooks"]["PreToolUse"][0]
    assert {"Bash", "Read", "Write", "Edit", "Glob", "Grep"} <= set(entry["matcher"].split("|"))
    assert "guard.py" in entry["hooks"][0]["command"]


# ------------------------------------------------------------------ cost per tool

def test_cost_per_tool_sums_to_the_total(workdir):
    tools = [Tool("big", "Big.", schema(), lambda: "x" * 3000), Tool("small", "Small.", schema(), lambda: "y")]
    client = FakeClaude(response(tool_use("1", "big"), tool_use("2", "small"), stop="tool_use"),
                        response(tool_use("3", "small"), stop="tool_use"), response(text("done")))
    trace = Trace(workdir / "trace.jsonl")
    Agent(client, "A", "system prompt", tools, trace).run("task")
    report = trace.by_tool
    assert sum(r["cost_usd"] for r in report.values()) == pytest.approx(trace.cost_usd(), abs=1e-12)
    assert sum(r["input_tokens"] + r["output_tokens"] for r in report.values()) == pytest.approx(trace.total_tokens)
    # the large result is re-read on the last call, so "big" owns more input than "small"
    assert report["big"]["input_tokens"] > report["small"]["input_tokens"]
    assert set(trace.by_agent_tool["A"]) == set(report)


def test_manifest_records_cost_by_tool_and_hooks(offline_run):
    m = json.loads(offline_run.path("manifest.json").read_text(encoding="utf-8"))
    assert sum(r["cost_usd"] for r in m["cost_by_tool"].values()) == pytest.approx(m["cost_usd"], abs=0.001)
    assert {"run_grid", "select_top5", "propose_strategies", "finalize", "build_deck"} <= set(m["cost_by_tool"])
    assert m["hooks"]["pre"] == ["forbid_delete", "confine_paths"]
    assert m["tool_calls"]["Research Agent"]["run_strategy"]["calls"] == 5
