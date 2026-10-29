"""Portfolio Manager Agent: picks the top strategies, proposes new ones, and makes the final call.

Round 1 (after the Research Agent's grid):
- `select_top5`: the agent must name the top strategies by total return over
  the common window. Code computes that ranking (`ranking.top_n`) and accepts
  only the exact set, so the selection is correct by construction; the agent
  supplies the rationale, a Pro and a Con for each.
- `propose_strategies`: the agent proposes new parameter sets (portfolio, SMA
  window, lookback) with a hypothesis, a Pro and a Con. Code rejects duplicates,
  out-of-range parameters, and any strategy that couldn't trade on every date of
  the common window (so all strategies stay comparable).

Round 2 (after the Research Agent runs the proposals):
- `finalize`: code applies the replacement rule (`ranking.apply_replacement`: a
  new strategy that beats the weakest of the top strategies on total return
  replaces it); the agent explains every kept, added and removed strategy.
- `write_meeting`: a one-page simulated conversation between the Portfolio
  Manager Agent and the analyst agents about what is compared, the objective,
  and why these strategies were picked. Rendered in the PDF, labelled simulated.
- `write_feedback`: two simulated one-page scripts of the PM reviewing the analyst
  agents: "Constructive Feedback" (correlation profiles and macro-basket returns)
  and "Harsh Feedback" (the process attacked through the strategies' real cons).
  Topics are checked in code; both are labelled simulated in the PDF.

All agent text is checked by the numeric and compliance guardrails.
"""

from strategy.agents import views
from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.config import PORTFOLIOS
from strategy.guardrails import check_text
from strategy.paths import write_json
from strategy.ranking import (RankingError, StrategySpec, apply_replacement, rule_text, run_strategy, top_n,
                              validate_proposal)

SPEAKERS = ("Portfolio Manager Agent", "Research Agent", "Analytics Agent")
MEETING_LINES = (8, 14)
MEETING_MAX_CHARS = 3600          # fits one PDF page at a readable size
MEETING_TOPICS = {"objective": ("objective", "goal"), "comparison": ("compar", "versus", " vs "),
                  "benchmark": ("spy",), "risk": ("drawdown", "volatility")}
# The two feedback pages (user request): the PM's review of the analyst agents' work, once constructive and once
# harsh. Each must cover these topics; the harsh page must use at least two of the strategies' real weaknesses.
FEEDBACK_LINES = (6, 12)
FEEDBACK_MAX_CHARS = 3200
FEEDBACK_TOPICS = {
    "constructive": {"correlation": ("correlat",), "returns": ("return",), "macro basket": ("basket", "macro")},
    "harsh": {},
}
HARSH_CONS = {"drawdowns": ("drawdown",), "volatility": ("volatil",), "no trading costs": ("cost",),
              "hindsight or overfitting": ("hindsight", "overfit", "cherry", "data-min", "data min"),
              "concentration": ("concentrat", "single etf", "one etf"), "lagging SPY": ("lag",)}

PROMPT = """You are the Portfolio Manager Agent at Agentic Capital Management, an AI-run research pipeline. You direct the Research Agent over two rounds.

The objective: find the strategies with the highest total return relative to SPY buy & hold over the common backtest window, while understanding the risk taken to get there (max drawdown, volatility, Sharpe). The strategy family: {rule}

Round 1:
1. Read the Research Agent's message (in your task) and call get_results(round=1). Use strategy_detail where it helps you judge a strategy.
2. Call select_top5 with the top {top} strategies by total return. The ranking is computed in code and only the exact top {top} is accepted. For each, give a one-sentence rationale, one Pro and one Con.
3. Call propose_strategies with exactly {k} NEW parameter sets for the Research Agent to test. Adjust parameters around what worked (for example, nearby lookbacks or SMA windows, or the other portfolio rule), and state a hypothesis, a Pro and a Con for each. Allowed: portfolio one of {portfolios}; sma 0 (the close) or {sma_lo}-{sma_hi} trading days; lookback_days {lb_lo}-{lb_hi}. A proposal must be new and must have enough price history to trade over the whole common window; the tool tells you if not. Include a short message_to_research.

Round 2:
1. Call get_results(round=2): the proposals' results and the replacement outcome computed by code. The rule: a new strategy that beats the weakest of the top {top} on total return replaces it.
2. Call finalize with a decision for every strategy in the final top {top} and every strategy removed: a rationale, a Pro and a Con. Add a 2-4 sentence message to all agents.
3. Call write_meeting: a simulated one-page meeting script of {lo}-{hi} lines between the Portfolio Manager Agent, the Research Agent and the Analytics Agent. It must cover what is being compared, the objective, the rationale for the strategies picked, and the risks (drawdown, volatility, SPY as the benchmark). All three speak at least twice.
4. Call write_feedback with two simulated one-page scripts ({flo}-{fhi} lines each) in which you, the Portfolio Manager Agent, review the analyst agents' (Research Agent and Analytics Agent) work, and they reply:
   - constructive: positive and encouraging, especially about the correlation profiles (the corr_spy figures, for example against QQQ's) and the returns earned by rotating across the macro basket of stocks, bonds, gold, oil and credit.
   - harsh: you are cruel and harsh. Tear into the analysts' process as sloppy, using the strategies' real cons (for example deep drawdowns, high volatility, no trading costs, hindsight selection from many tested combinations, single-ETF concentration, years it lagged SPY), and imply they should be fired for it. The targets are AI agents, so no slurs and nothing about protected characteristics.

Rules: quote only numbers the tools return, exactly as displayed (percentages to 1 decimal, ratios to 2), or the parameters of a strategy. Never compute new numbers yourself. Name the strategy every figure belongs to; a range must be the true minimum and maximum of the strategies you name. No promises about future returns, no urgency, no names of people. If a tool rejects your input, fix exactly what it reports and resubmit. When done, reply with one line."""


def build(ctx, round_):
    """Build the Portfolio Manager Agent for one round.

    Args:
        ctx: the run context.
        round_: 1 (select the top strategies and propose new ones) or 2 (finalize and write the meeting).

    Returns:
        A configured `Agent`.
    """
    cfg = ctx.cfg.ranking
    round1_ids = lambda: ctx.research[1]["ids"]

    def checked(texts, extra=()):
        """Guardrail-check agent texts; raise a ToolError listing every problem."""
        index = ctx.number_index(extra)
        problems = [f"{t[:60]!r}: {p}" for t in texts for p in check_text(t, index)]
        if problems:
            raise ToolError("Fix these and resubmit:\n" + "\n".join(problems))

    def get_results(round):
        if round != round_:
            raise ToolError(f"This is round {round_}.")
        ctx.record("get_results", round=round)
        if round_ == 1:
            return {"window": views.window(ctx), "benchmarks": views.benchmarks(ctx),
                    "strategies_ranked_by_total_return": views.ranked(ctx, round1_ids())}
        new_ids = [p["id"] for p in ctx.pm["proposals"]]
        outcome = apply_replacement(ctx.scores, [p["id"] for p in ctx.pm["top5"]], new_ids)
        return {"window": views.window(ctx), "benchmarks": views.benchmarks(ctx),
                "round1_top": views.ranked(ctx, [p["id"] for p in ctx.pm["top5"]]),
                "proposals": views.ranked(ctx, new_ids),
                "replacements": [{"added": views.row(ctx, r["added"]), "removed": views.row(ctx, r["removed"])}
                                 for r in outcome["replacements"]],
                "final_top": views.ranked(ctx, outcome["final"]),
                "research_message": ctx.research[2]["message"], "research_findings": ctx.research[2]["findings"]}

    def strategy_detail(id):
        if id not in ctx.specs:
            raise ToolError(f"Unknown strategy {id!r}.")
        ctx.record("strategy_detail", id=id)
        if id not in ctx.picks:
            ctx.picks[id] = run_strategy(ctx.prices[list(cfg.universe)], ctx.specs[id])[1]
        picks = views.scored_picks(ctx.picks[id], ctx.window_start)
        led = picks[0].value_counts(normalize=True)
        ctx.facts.setdefault("leader_share", {})[id] = {t: float(v) for t, v in led.items()}
        return {**views.row(ctx, id), "share_of_months_each_etf_led": {t: f"{v * 100:.1f}%" for t, v in led.items()},
                "leader_changes": int((picks[0] != picks[0].shift()).iloc[1:].sum())}

    def select_top5(picks):
        if round_ != 1 or "get_results" not in ctx.calls:
            raise ToolError("Call get_results(round=1) first.")
        expected = top_n(ctx.scores, cfg.top_n, round1_ids())
        given = [p["id"] for p in picks]
        if sorted(given) != sorted(expected):
            raise ToolError(f"The top {cfg.top_n} by total return are not {sorted(given)}. Re-read get_results: "
                            "pick the highest total returns.")
        checked([t for p in picks for t in (p["rationale"], p["pro"], p["con"])])
        order = {sid: i for i, sid in enumerate(expected)}
        ctx.pm["top5"] = sorted(picks, key=lambda p: order[p["id"]])
        ctx.record("select_top5")
        return {"accepted": expected}

    def propose(proposals, message_to_research):
        if "top5" not in ctx.pm:
            raise ToolError("Select the top strategies first.")
        if len(proposals) != cfg.n_proposals:
            raise ToolError(f"Propose exactly {cfg.n_proposals} strategies.")
        existing, problems, accepted = set(ctx.specs), [], []
        for p in proposals:
            spec = StrategySpec(p["portfolio"], p["sma"], p["lookback_days"])
            try:
                validate_proposal(spec, cfg, existing)
                rets, _ = run_strategy(ctx.prices[list(cfg.universe)], spec)
                if rets.index[0] > ctx.window_start:
                    raise RankingError(f"{spec.id} needs more history: its first trading day is "
                                       f"{rets.index[0].date()}, after the window start {ctx.window_start.date()}. "
                                       "Use a shorter SMA window or lookback.")
            except RankingError as exc:
                problems.append(str(exc))
                continue
            existing.add(spec.id)
            accepted.append({**spec.to_dict(), "hypothesis": p["hypothesis"], "pro": p["pro"], "con": p["con"]})
        if problems:
            raise ToolError("Fix these proposals and resubmit all of them:\n" + "\n".join(problems))
        params = [v for p in accepted for v in (p["sma"], p["lookback_days"])]
        checked([message_to_research, *[t for p in accepted for t in (p["hypothesis"], p["pro"], p["con"])]], params)
        ctx.pm["proposals"] = accepted
        ctx.pm["message_to_research"] = message_to_research
        ctx.record("propose_strategies")
        ctx.say("Portfolio Manager Agent", "Research Agent", 1, message_to_research,
                [{"kind": "top", **p} for p in ctx.pm["top5"]] + [{"kind": "proposal", **p} for p in accepted])
        write_json(ctx.path("pm.json"), ctx.pm)
        return {"accepted": [p["id"] for p in accepted]}

    def finalize(decisions, message):
        if round_ != 2 or "get_results" not in ctx.calls:
            raise ToolError("Call get_results(round=2) first.")
        outcome = apply_replacement(ctx.scores, [p["id"] for p in ctx.pm["top5"]], [p["id"] for p in ctx.pm["proposals"]])
        removed = [r["removed"] for r in outcome["replacements"]]
        required = set(outcome["final"]) | set(removed)
        given = {d["id"] for d in decisions}
        if given != required:
            raise ToolError(f"Give exactly one decision for each of {sorted(required)} "
                            f"(the final top {cfg.top_n} and every removed strategy); got {sorted(given)}.")
        checked([message, *[t for d in decisions for t in (d["rationale"], d["pro"], d["con"])]])
        added = {r["added"] for r in outcome["replacements"]}
        status = lambda sid: "removed" if sid in removed else "added" if sid in added else "kept"
        ctx.pm["final"] = {**outcome, "decisions": [{**d, "status": status(d["id"])} for d in decisions],
                           "message": message}
        ctx.record("finalize")
        ctx.say("Portfolio Manager Agent", "All agents", 2, message, ctx.pm["final"]["decisions"])
        write_json(ctx.path("pm.json"), ctx.pm)
        return {"final": outcome["final"], "replacements": outcome["replacements"]}

    def write_meeting(lines):
        if "final" not in ctx.pm:
            raise ToolError("Finalize first.")
        lo, hi = MEETING_LINES
        if not lo <= len(lines) <= hi:
            raise ToolError(f"Write {lo}-{hi} lines.")
        counts = {s: sum(line["speaker"] == s for line in lines) for s in SPEAKERS}
        if min(counts.values()) < 2:
            raise ToolError(f"Each of {list(SPEAKERS)} must speak at least twice; got {counts}.")
        body = " ".join(line["text"] for line in lines)
        if len(body) > MEETING_MAX_CHARS:
            raise ToolError(f"The script is {len(body)} characters; keep it under {MEETING_MAX_CHARS} to fit one page.")
        missing = [t for t, words in MEETING_TOPICS.items() if not any(w in body.lower() for w in words)]
        if missing:
            raise ToolError(f"The meeting must cover: {missing} (what is compared, the objective, SPY, and risk).")
        checked([line["text"] for line in lines])
        ctx.pm["meeting"] = lines
        ctx.record("write_meeting")
        write_json(ctx.path("pm.json"), ctx.pm)
        return {"saved": len(lines)}

    def write_feedback(constructive, harsh):
        """Validate and save the two feedback scripts (rendered as the "Constructive Feedback" and
        "Harsh Feedback" pages). Raises ToolError listing every problem across both scripts."""
        if "meeting" not in ctx.pm:
            raise ToolError("Write the meeting first.")
        problems = []
        lo, hi = FEEDBACK_LINES
        for kind, lines in (("constructive", constructive), ("harsh", harsh)):
            if not lo <= len(lines) <= hi:
                problems.append(f"{kind}: write {lo}-{hi} lines (got {len(lines)}).")
            pm_lines = sum(line["speaker"] == "Portfolio Manager Agent" for line in lines)
            analysts = {line["speaker"] for line in lines} - {"Portfolio Manager Agent"}
            if pm_lines < 3 or not analysts:
                problems.append(f"{kind}: the Portfolio Manager Agent speaks at least 3 times and an analyst agent replies.")
            body = " ".join(line["text"] for line in lines).lower()
            if len(body) > FEEDBACK_MAX_CHARS:
                problems.append(f"{kind}: {len(body)} characters; keep it under {FEEDBACK_MAX_CHARS} to fit one page.")
            missing = [t for t, words in FEEDBACK_TOPICS[kind].items() if not any(w in body for w in words)]
            if missing:
                problems.append(f"{kind}: must cover {missing}.")
            if kind == "harsh":
                used = [c for c, words in HARSH_CONS.items() if any(w in body for w in words)]
                if len(used) < 2:
                    problems.append(f"harsh: criticize the process with at least two real cons from {list(HARSH_CONS)}.")
        if problems:
            raise ToolError("Fix these and resubmit both scripts:\n" + "\n".join(problems))
        checked([line["text"] for line in constructive + harsh])
        ctx.pm["feedback"] = {"constructive": constructive, "harsh": harsh}
        ctx.record("write_feedback")
        write_json(ctx.path("pm.json"), ctx.pm)
        return {"saved": {"constructive": len(constructive), "harsh": len(harsh)}}

    text_item = {"type": "string"}
    tools = [
        Tool("get_results", "Ranked results for this round, with SPY and QQQ buy & hold.",
             schema({"round": {"type": "integer", "enum": [round_]}}, ["round"]), get_results),
        Tool("strategy_detail", "Detail for one strategy: metrics, how often each ETF led, leader changes.",
             schema({"id": {"type": "string"}}, ["id"]), strategy_detail),
    ]
    if round_ == 1:
        pick = {"type": "object", "additionalProperties": False, "required": ["id", "rationale", "pro", "con"],
                "properties": {"id": text_item, "rationale": text_item, "pro": text_item, "con": text_item}}
        proposal = {"type": "object", "additionalProperties": False,
                    "required": ["portfolio", "sma", "lookback_days", "hypothesis", "pro", "con"],
                    "properties": {"portfolio": {"type": "string", "enum": list(PORTFOLIOS)},
                                   "sma": {"type": "integer", "description": "0 = the close"},
                                   "lookback_days": {"type": "integer"}, "hypothesis": text_item,
                                   "pro": text_item, "con": text_item}}
        tools += [
            Tool("select_top5", f"Select the top {cfg.top_n} strategies by total return, with a rationale, Pro and Con each.",
                 schema({"picks": {"type": "array", "items": pick, "minItems": cfg.top_n, "maxItems": cfg.top_n}},
                        ["picks"]), select_top5),
            Tool("propose_strategies", f"Propose {cfg.n_proposals} new parameter sets for the Research Agent to run.",
                 schema({"proposals": {"type": "array", "items": proposal},
                         "message_to_research": text_item}, ["proposals", "message_to_research"]), propose),
        ]
    else:
        decision = {"type": "object", "additionalProperties": False, "required": ["id", "rationale", "pro", "con"],
                    "properties": {"id": text_item, "rationale": text_item, "pro": text_item, "con": text_item}}
        line = {"type": "object", "additionalProperties": False, "required": ["speaker", "text"],
                "properties": {"speaker": {"type": "string", "enum": list(SPEAKERS)}, "text": text_item}}
        tools += [
            Tool("finalize", "Record the final decision for every final and removed strategy, and a message to all agents.",
                 schema({"decisions": {"type": "array", "items": decision}, "message": text_item},
                        ["decisions", "message"]), finalize),
            Tool("write_meeting", "Save the one-page simulated meeting script.",
                 schema({"lines": {"type": "array", "items": line}}, ["lines"]), write_meeting),
            Tool("write_feedback", "Save the two simulated feedback scripts: constructive and harsh.",
                 schema({"constructive": {"type": "array", "items": line}, "harsh": {"type": "array", "items": line}},
                        ["constructive", "harsh"]), write_feedback),
        ]
    prompt = PROMPT.format(rule=rule_text(cfg), top=cfg.top_n, k=cfg.n_proposals,
                           portfolios=", ".join(PORTFOLIOS), sma_lo=cfg.sma_range[0], sma_hi=cfg.sma_range[1],
                           lb_lo=cfg.lookback_range[0], lb_hi=cfg.lookback_range[1],
                           lo=MEETING_LINES[0], hi=MEETING_LINES[1], flo=FEEDBACK_LINES[0], fhi=FEEDBACK_LINES[1])
    return Agent(ctx.client, "Portfolio Manager Agent", prompt, tools, ctx.trace, effort="medium",
                 max_turns=ctx.cfg.max_turns_per_agent, token_budget=ctx.cfg.token_budget, model=ctx.cfg.model,
                 hooks=ctx.hooks)


def task(ctx, round_):
    """The PM Agent's task message for `round_`, including the Research Agent's latest message."""
    r = ctx.research[round_]
    findings = "\n".join(f"- {f}" for f in r["findings"])
    if round_ == 1:
        return (f"Round 1. Message from the Research Agent:\n{r['message']}\n\nFindings:\n{findings}\n\n"
                "Select the top strategies and propose new ones.")
    return (f"Round 2. Message from the Research Agent:\n{r['message']}\n\nFindings:\n{findings}\n\n"
            "Make the final decision, then write the meeting script and the two feedback scripts.")
