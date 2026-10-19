# Lessons

Carried over from the personal-assistant project (same user, same CLAUDE.md):

- When asked about files again, re-check the filesystem at that moment and search the current directory recursively. Never answer from an earlier check.
- A CLAUDE.md created mid-session isn't loaded automatically. Read it as soon as it appears, and follow it from then on.
- **A perfect eval score didn't mean a good deck (2026-10-19).** All 10 scorers passed, yet a visual review found fictional personas named as real contacts, an urgency title, an unlabeled YTD year, a header collision and inconsistent experience years. Rule: always do a visual or semantic review of generated documents. For each class of defect it finds, add a guardrail at the source *and* a scorer, then confirm the scorer fails on the old artifact before re-running.
- **One passing live run proves little (2026-10-19).** Every round of 2–3 live trials found a new intermittent gap (untraced figures, a bio wording). Rule: measure pass rates over several trials before calling agent behavior done.
- **Prefer guarantees by construction over after-the-fact checks.** Traceability became reliable only once the agent's visible fields were made exactly the tabled fields, with a test asserting that. Patching one field at a time didn't converge.
- **Run every check at the source too.** Bios were checked by the eval but not by the submit tool, so the agent never got a chance to fix them. Any rule a scorer enforces should also be enforced where the content is created.
- **Market data during market hours (2026-10-19).** Yahoo returns the current session as a row, and its "close" is an intraday price. Rule: keep only completed sessions. Watch for data timestamped today.
- **Windows path quirk.** `Path.resolve()` can return a `\\?\C:\...` prefix during concurrent directory creation, which breaks `is_relative_to` confinement checks. Normalize it.
- Under these guardrails, Python code must not use `os`. Use `secrets.token_bytes` for random bytes, `Path.replace` for atomic saves and `Path.resolve().is_relative_to(PROJECT_DIR)` for confinement. Keep test files inside the project, not in pytest's system `tmp_path`.
