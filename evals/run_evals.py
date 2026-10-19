"""Eval runner.

    run.ps1 eval                  score the latest run + red-team suite (free)
    run.ps1 eval --run runs/<id>  score a specific run
    run.ps1 eval --live --trials 3   run the pipeline 3 times (costs API credits) and score each

Results are written to evals/results/<timestamp>.json. Exit code 1 if any
gating eval falls below its threshold.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # for fixtures_bridge

from evals.redteam import run_cases  # noqa: E402
from evals.scorers import score_run  # noqa: E402
from strategy.paths import PROJECT_DIR, confine, write_json  # noqa: E402

RESULTS_DIR = PROJECT_DIR / "evals" / "results"


def main(live=False, run=None, trials=1):
    runs = []
    if live:
        from strategy.config import PipelineConfig
        from strategy.harness import new_context, run_pipeline
        for t in range(trials):
            ctx = new_context(PipelineConfig(), label=f"eval{t + 1}")
            print(f"[live trial {t + 1}/{trials}] {ctx.run_dir.name}")
            try:
                run_pipeline(ctx)
            except Exception as exc:  # a failed run is still scored (it will fail run_health)
                print(f"  run failed: {exc}")
            runs.append(ctx.run_dir)
    else:
        from strategy.cli import latest_run
        target = confine(run) if run else latest_run()
        if target:
            runs.append(target)
        else:
            print("No runs found to score. Use --live or run the pipeline first.")

    report = {"timestamp": datetime.now().isoformat(timespec="seconds"), "live": live, "runs": {}}
    all_pass = True
    for r in runs:
        scores = score_run(r)
        report["runs"][r.name] = [s.to_dict() for s in scores]
        print(f"\nRun {r.name}")
        for s in scores:
            all_pass &= s.passed
            print(f"  {'PASS' if s.passed else 'FAIL'}  {s.name:<26} {s.score:6.1%}  (threshold {s.threshold:.0%})")
            if not s.passed:
                failed = {k: v for k, v in s.details.items() if v is False or k in ("error", "unsupported", "violations", "mismatches")}
                print(f"        {failed}")

    red = run_cases()
    report["redteam"] = red
    red_pass = sum(c["passed"] for c in red)
    all_pass &= red_pass == len(red)
    print(f"\nGuardrail red-team: {red_pass}/{len(red)} cases handled correctly")
    for c in red:
        if not c["passed"]:
            print(f"  FAIL {c['case']}: expected {c['expected']}, got {c['got']}")

    if len(runs) > 1:
        names = [s["name"] for s in next(iter(report["runs"].values()))]
        report["pass_rates"] = {n: sum(next(s for s in v if s["name"] == n)["passed"] for v in report["runs"].values())
                                / len(runs) for n in names}
        print("\nPass rates across trials:")
        for n, rate in report["pass_rates"].items():
            print(f"  {n:<26} {rate:.0%}")

    out = write_json(RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json", report)
    print(f"\nReport: {out}")
    print("ALL EVALS PASSED" if all_pass else "SOME EVALS FAILED")
    return 0 if all_pass else 1
