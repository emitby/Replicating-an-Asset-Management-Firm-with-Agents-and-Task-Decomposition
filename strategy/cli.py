"""Command line: run the pipeline, re-run a stage, run evals, render PDF pages.

Always launch through run.ps1 / run.sh, which keep library caches inside the project.

    run.ps1 run [--offline]
    run.ps1 stage presentation --from runs/<id>
    run.ps1 eval [--live] [--run runs/<id>] [--trials N]
    run.ps1 render-pages runs/<id>
    run.ps1 test
"""

import argparse
import json
import sys
from pathlib import Path

from strategy.config import PipelineConfig
from strategy.paths import RUNS_DIR, confine


def main(argv=None):
    p = argparse.ArgumentParser(prog="strategy", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the full five-agent pipeline")
    r.add_argument("--offline", action="store_true", help="use cached prices instead of Yahoo Finance")
    s = sub.add_parser("stage", help="re-run one stage from an earlier run's artifacts")
    s.add_argument("name", choices=["data", "backtest", "analytics", "team", "presentation"])
    s.add_argument("--from", dest="source", required=True, type=Path)
    s.add_argument("--offline", action="store_true")
    e = sub.add_parser("eval", help="score runs against the eval suite")
    e.add_argument("--live", action="store_true", help="run the pipeline (costs API credits) and score it")
    e.add_argument("--run", type=Path, help="score an existing run (default: latest)")
    e.add_argument("--trials", type=int, default=1)
    g = sub.add_parser("render-pages", help="render PDF pages to PNG for review")
    g.add_argument("run", type=Path)
    args = p.parse_args(argv)

    if args.cmd == "run":
        from strategy.harness import new_context, run_pipeline
        ctx = new_context(PipelineConfig(offline=args.offline))
        print(f"Run directory: {ctx.run_dir}")
        run_pipeline(ctx)
        _summary(ctx.run_dir)
    elif args.cmd == "stage":
        from strategy.harness import new_context, rerun_stage
        ctx = new_context(PipelineConfig(offline=args.offline), label=f"stage-{args.name}")
        print(f"Run directory: {ctx.run_dir}")
        rerun_stage(ctx, args.name, confine(args.source))
        _summary(ctx.run_dir)
    elif args.cmd == "eval":
        from evals.run_evals import main as eval_main
        sys.exit(eval_main(live=args.live, run=args.run, trials=args.trials))
    elif args.cmd == "render-pages":
        from evals.scorers import render_pages
        for path in render_pages(confine(args.run)):
            print(path)


def _summary(run_dir):
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    print(f"Status: {m['status']}  |  {m['seconds']}s  |  ${m['cost_usd']:.2f}  |  tokens {sum(m['usage_tokens'].values()):,}")
    if (run_dir / "presentation.pdf").exists():
        print(f"PDF: {run_dir / 'presentation.pdf'}")


def latest_run():
    """The newest finished run folder (one with a ``manifest.json``), or ``None``.

    Returns ``None`` when ``runs/`` doesn't exist yet: a fresh clone (or CI) has never run
    the pipeline, and ``eval`` should say "No runs found" rather than crash.
    """
    root = confine(RUNS_DIR)
    if not root.is_dir():
        return None
    runs = sorted((d for d in root.iterdir() if (d / "manifest.json").exists()), key=lambda d: d.name)
    return runs[-1] if runs else None


if __name__ == "__main__":
    main()
