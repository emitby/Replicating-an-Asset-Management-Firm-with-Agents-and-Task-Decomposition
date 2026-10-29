"""Data Agent: fetches the seven-ETF universe and ^IRX from Yahoo Finance and certifies the dataset."""

from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.config import ALLOWED_TICKERS, UNIVERSE
from strategy.data import DataError, clean, dataset_hash, fetch_prices, quality_report
from strategy.paths import write_json, write_text

PROMPT = """You are the Data Agent at Agentic Capital Management, an AI-run research pipeline. You prepare the daily price dataset for a month-end ETF ranking strategy across {universe}.

Your job:
1. Fetch adjusted daily closes for {universe} and ^IRX (the 13-week T-bill yield, used as the risk-free rate), starting from the requested date.
2. Run the quality check and read it carefully: missing values, gaps, suspicious jumps, stale prices, implausible yields.
3. Save the dataset. Saving keeps only days when every ETF traded and only completed sessions, and carries the T-bill yield forward over its own holidays.
4. Reply with a short data note: date range, row count, any issues found and how they were handled, and anything downstream agents should know.

Rules: only the allowed tickers exist for this pipeline. If a fetch fails, retry once, then report the failure clearly. Never invent data or statistics: report only what the tools return.""".format(universe=", ".join(UNIVERSE))


def build(ctx):
    def fetch(tickers, start):
        ctx.record("fetch_prices", tickers=tickers, start=start)
        try:
            df = fetch_prices(tickers, start, offline=ctx.cfg.offline)
        except DataError as exc:
            raise ToolError(str(exc)) from None
        ctx.raw = df if ctx.raw is None else df.combine_first(ctx.raw)
        return {t: {"first": str(df[t].first_valid_index().date()), "last": str(df[t].last_valid_index().date()),
                    "rows": int(df[t].notna().sum())} for t in df.columns}

    def check():
        if ctx.raw is None:
            raise ToolError("Fetch prices first.")
        ctx.record("check_data_quality")
        ctx.data_report = quality_report(ctx.raw)
        return ctx.data_report

    def save():
        if ctx.raw is None:
            raise ToolError("Fetch prices first.")
        if "check_data_quality" not in ctx.calls:
            raise ToolError("Run check_data_quality before saving.")
        try:
            ctx.prices = clean(ctx.raw)
        except DataError as exc:
            raise ToolError(str(exc)) from None
        ctx.record("save_dataset")
        report = dict(ctx.data_report or {}, cleaned_rows=len(ctx.prices),
                      cleaned_start=str(ctx.prices.index.min().date()),
                      cleaned_end=str(ctx.prices.index.max().date()),
                      sha256_16=dataset_hash(ctx.prices), source="Yahoo Finance via yfinance (auto_adjust=True)",
                      offline_cache=ctx.cfg.offline)
        ctx.data_report = report
        write_text(ctx.path("prices.csv"), ctx.prices.to_csv())
        write_json(ctx.path("data_report.json"), report)
        return {"saved": "prices.csv", "rows": len(ctx.prices), "start": report["cleaned_start"],
                "end": report["cleaned_end"], "hash": report["sha256_16"]}

    tools = [
        Tool("fetch_prices", f"Download adjusted daily closes from Yahoo Finance. Allowed tickers: {list(ALLOWED_TICKERS)}.",
             schema({"tickers": {"type": "array", "items": {"type": "string", "enum": list(ALLOWED_TICKERS)}, "minItems": 1},
                     "start": {"type": "string", "description": "YYYY-MM-DD"}}, ["tickers", "start"]), fetch),
        Tool("check_data_quality", "Quality report on the fetched data: missing values, gaps, jumps, stale runs, yield range.",
             schema(), check),
        Tool("save_dataset", "Clean and save the dataset for the research. Requires a quality check first.", schema(), save),
    ]
    return Agent(ctx.client, "Data Agent", PROMPT, tools, ctx.trace, effort="low",
                 max_turns=ctx.cfg.max_turns_per_agent, token_budget=ctx.cfg.token_budget, model=ctx.cfg.model,
                 hooks=ctx.hooks)


def task(ctx):
    return f"Prepare the dataset starting {ctx.cfg.ranking.start} through the latest available close."
