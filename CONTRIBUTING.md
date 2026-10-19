# Contributing

## Setup

```bash
python -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt     # Windows: .venv\Scripts\python.exe -m pip ...
./run.sh test                                               # Windows: .\run.ps1 test
```

Always use the launcher. It keeps library caches inside the project.

## Ground rules

These follow [CLAUDE.md](CLAUDE.md), which applies to human and AI contributors alike.

1. **Stay inside the project directory.** No `import os` (a test enforces this). Route all file I/O through `strategy.paths`. Never delete files.
2. **Agents decide, code computes.** Every number that reaches the PDF must come from a tool. New metrics go in `analytics.py`, with tests.
3. **Traceability.** If the Presentation Agent can see a value, a code-generated page must show it. `test_every_citable_percentage_is_traceable_in_pdf` enforces this.
4. **Enforce at the source and in evals.** A new content rule needs a tool-time check (so the agent can fix it), a scorer in `evals/scorers.py` and a red-team case in `evals/redteam.py`. Confirm the scorer fails on an artifact that breaks the rule.
5. **Compliance content belongs to code.** Disclosures, in-sample labels and fictional-persona stamps are rendered by `pdf.py`, never written by agents.
6. **Verify live.** Prompt or agent changes need `run.ps1 eval --live --trials 3`. One passing run isn't evidence.
7. **Plan and record.** For non-trivial work, plan in `tasks/todo.md` and record what you learned in `tasks/lessons.md`.

## Pull requests

Keep changes focused, with tests. CI runs the offline suite on Python 3.10–3.12. Live evals need an API key, so run them locally and paste the pass-rate table into the PR.
