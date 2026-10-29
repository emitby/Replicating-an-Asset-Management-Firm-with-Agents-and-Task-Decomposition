"""Token profile of every agent tool: definition tokens and result tokens, measured exactly.

    .venv\\Scripts\\python.exe -m evals.token_profile runs\\<id> [--markdown docs/token-usage.md]

Uses the Messages token-counting endpoint (free; no model output is generated):
- System prompt tokens: count(system=prompt) - count(no system).
- Tool definition tokens (marginal): count(all tools) - count(all tools except this one).
  "Tool-use overhead" = count(all tools) - count(no tools) - sum(marginals): the fixed cost of
  enabling tool use at all.
- Tool result tokens: for every tool call in the run's trace.jsonl, the exact text that was
  returned to the model is counted as a user message, minus the empty-message baseline.

Definitions are sent on every model turn of that agent (prompt caching makes repeats cheap);
results are sent once and then stay in that agent's context for its remaining turns.
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import anthropic

from strategy.agents import analytics_agent, data_agent, pm_agent, presentation_agent, research_agent, team_agent
from strategy.agents.runtime import MODEL, Trace
from strategy.config import PipelineConfig
from strategy.context import RunContext
from strategy.paths import confine, write_json, write_text

# Agent name -> builders. The Research and Portfolio Manager Agents have a different tool set in each round;
# their definitions are profiled over the union of both rounds' tools.
AGENTS = {"Data Agent": [data_agent.build],
          "Research Agent": [lambda ctx: research_agent.build(ctx, 1), lambda ctx: research_agent.build(ctx, 2)],
          "Portfolio Manager Agent": [lambda ctx: pm_agent.build(ctx, 1), lambda ctx: pm_agent.build(ctx, 2)],
          "Analytics Agent": [analytics_agent.build], "Team Agent": [team_agent.build],
          "Presentation Agent": [presentation_agent.build]}
PROBE = [{"role": "user", "content": "x"}]


def count(client, **kw):
    return client.messages.count_tokens(model=MODEL, messages=kw.pop("messages", PROBE), **kw).input_tokens


def definition_profile(client, ctx):
    out = {}
    base = count(client)
    for name, builders in AGENTS.items():
        agents = [b(ctx) for b in builders]
        agent = agents[0]
        params = list({t["name"]: t for a in agents for t in a.tool_params}.values())
        system = count(client, system=agent.system) - base
        all_tools = count(client, tools=params)
        marginals = {}
        for i, t in enumerate(params):
            rest = params[:i] + params[i + 1:]
            marginals[t["name"]] = all_tools - (count(client, tools=rest) if rest else base)
        overhead = all_tools - base - sum(marginals.values()) if len(params) > 1 else 0
        out[name] = {"system_prompt_tokens": system, "tool_definition_tokens": marginals,
                     "tool_use_overhead_tokens": overhead, "all_definitions_tokens": all_tools - base,
                     "effort": agent.effort}
    return out


def result_profile(client, run_dir):
    events = [json.loads(l) for l in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if l]
    base = count(client)
    per = defaultdict(list)
    for e in events:
        if e.get("type") == "tool" and "result" in e:
            tokens = count(client, messages=[{"role": "user", "content": e["result"] or " "}]) - base + 1
            per[(e["agent"], e["tool"])].append({"tokens": tokens, "ok": e["ok"]})
    usage = defaultdict(lambda: defaultdict(int))
    for e in events:
        if e.get("type") == "model":
            u = usage[e["agent"]]
            u["model_turns"] += 1
            for k, v in e["usage"].items():
                u[k] += v
    return per, {a: dict(u) for a, u in usage.items()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--markdown", type=Path, help="also write a markdown report to this path")
    args = ap.parse_args(argv)
    run_dir = confine(args.run)
    client = anthropic.Anthropic()
    ctx = RunContext(run_dir=run_dir, cfg=PipelineConfig(), trace=Trace(run_dir / "trace.jsonl"), client=None)
    defs = definition_profile(client, ctx)
    results, usage = result_profile(client, run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    report = {"run": run_dir.name, "model": MODEL, "definitions": defs, "usage_by_agent": usage,
              "cost_by_agent_usd": manifest.get("cost_by_agent_usd"), "tools": []}
    for agent, d in defs.items():
        for tool, def_tokens in d["tool_definition_tokens"].items():
            calls = results.get((agent, tool), [])
            toks = [c["tokens"] for c in calls]
            report["tools"].append({
                "agent": agent, "tool": tool, "definition_tokens": def_tokens, "calls": len(calls),
                "cost_usd_run": (manifest.get("cost_by_tool") or {}).get(tool, {}).get("cost_usd", 0.0),
                "errors": sum(1 for c in calls if not c["ok"]),
                "result_tokens_mean": round(statistics.mean(toks)) if toks else 0,
                "result_tokens_max": max(toks) if toks else 0, "result_tokens_total": sum(toks)})
    write_json(run_dir / "token_profile.json", report)

    lines = [f"Run `{run_dir.name}` · model `{MODEL}` · exact counts from the token-counting endpoint", "",
             "| Agent | Tool | Definition tokens | Calls | Result tokens (mean) | Result tokens (max) | Result tokens (total) | Cost (run) |",
             "|---|---|---|---|---|---|---|---|"]
    for t in report["tools"]:
        lines.append(f"| {t['agent']} | `{t['tool']}` | {t['definition_tokens']} | {t['calls']}"
                     f"{' (' + str(t['errors']) + ' err)' if t['errors'] else ''} | {t['result_tokens_mean']:,} | "
                     f"{t['result_tokens_max']:,} | {t['result_tokens_total']:,} | ${t['cost_usd_run']:.3f} |")
    lines += ["", "| Agent | Effort | System prompt tokens | All tool definitions | Tool-use overhead | Model turns | "
              "Input (uncached) | Cache write | Cache read | Output | Cost |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for agent, d in defs.items():
        u = usage.get(agent, {})
        cost = (manifest.get("cost_by_agent_usd") or {}).get(agent, 0)
        lines.append(f"| {agent} | {d['effort']} | {d['system_prompt_tokens']:,} | {d['all_definitions_tokens']:,} | "
                     f"{d['tool_use_overhead_tokens']:,} | {u.get('model_turns', 0)} | {u.get('input', 0):,} | "
                     f"{u.get('cache_write', 0):,} | {u.get('cache_read', 0):,} | {u.get('output', 0):,} | ${cost:.3f} |")
    md = "\n".join(lines) + "\n"
    print(md)
    if args.markdown:
        write_text(args.markdown, md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
