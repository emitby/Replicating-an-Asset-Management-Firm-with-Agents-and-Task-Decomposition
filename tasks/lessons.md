# Lessons

Carried over from the personal-assistant project (same user, same CLAUDE.md):

- When asked about files again, re-check the filesystem at that moment and search the current directory recursively. Never answer from an earlier check.
- A CLAUDE.md created mid-session isn't loaded automatically. Read it as soon as it appears, and follow it from then on.
- **A perfect eval score didn't mean a good deck (2026-10-19).** All 10 scorers passed, yet a visual review found fictional personas named as real contacts, an urgency title, an unlabeled YTD year, a header collision and inconsistent experience years. Rule: always do a visual or semantic review of generated documents. For each class of defect it finds, add a guardrail at the source *and* a scorer, then confirm the scorer fails on the old artifact before re-running.
- **One passing live run proves little (2026-10-19).** Every round of 2–3 live trials found a new intermittent gap (untraced figures, a bio wording). Rule: measure pass rates over several trials before calling agent behavior done.
- **Prefer guarantees by construction over after-the-fact checks.** Traceability became reliable only once the agent's visible fields were made exactly the tabled fields, with a test asserting that. Patching one field at a time didn't converge.
- **Run every check at the source too.** Bios were checked by the eval but not by the submit tool, so the agent never got a chance to fix them. Any rule a scorer enforces should also be enforced where the content is created.
- **ReportLab drops content silently when a Frame is too small (seen twice: a footnote, then a page title).** Rule: wrap any variable-length text in `KeepInFrame(mode="shrink")`, and assert in tests that the expected text appears in the extracted PDF.
- **Code-owned text must be true on every page it appears on.** The performance footer was written for one strategy and became false when a second was added. Rule: when adding a feature, re-read every boilerplate string that applies to it.
- **Keyword co-occurrence is a weak proxy for meaning.** A slide-level check passed without the claim ever being made. Rule: check at the smallest unit that carries the claim (the bullet), and test the check against a known-bad artifact.
- **An independent cross-check is cheap insurance.** A standalone implementation written without importing project code confirmed the momentum engine exactly. Keep it in the repo as an eval.
- **A regression test must be shown to fail on the defect it targets.** The first overlap test (a word search) passed on the very PDF with the overlap. Only a test confirmed to fail on the bad artifact counts.
- **Pattern-based exclusions drift with agent wording.** "N-month momentum" vs "N-month lookback": the agent chose a title style the regex didn't anticipate. Match the semantic markers broadly, and test with the variants actually seen in live runs.
- **State the modeling assumption implied by the user's words.** "Allocate 50/30/20 for the next month" means monthly rebalancing with drift, not constant daily weights. Check that the implementation matches the plain-language rule before running.
- **Layout must adapt to the data's shape.** Tables sized for 6 series broke at 8. Compute widths from the available space, and assert non-overlap.
- **Market data during market hours (2026-10-19).** Yahoo returns the current session as a row, and its "close" is an intraday price. Rule: keep only completed sessions. Watch for data timestamped today.
- **Windows path quirk.** `Path.resolve()` can return a `\\?\C:\...` prefix during concurrent directory creation, which breaks `is_relative_to` confinement checks. Normalize it.
- Under these guardrails, Python code must not use `os`. Use `secrets.token_bytes` for random bytes, `Path.replace` for atomic saves and `Path.resolve().is_relative_to(PROJECT_DIR)` for confinement. Keep test files inside the project, not in pytest's system `tmp_path`.
