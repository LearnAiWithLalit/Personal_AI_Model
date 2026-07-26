---
name: guardian-verify
description: Gather fresh evidence immediately before claiming a task is complete, fixed, passing, or ready to merge. Use after implementation and review, and before commits, pushes, pull requests, releases, or completion reports.
---

# Guardian Verify

1. Identify the command or observation that proves each acceptance criterion.
2. Run the complete verification now; do not reuse a worker claim or stale result.
3. Read the exit code, failures, warnings, and relevant output.
4. Inspect the current diff and confirm only intended files changed.
5. Compare evidence against confirmed requirements.
6. Report exact evidence, limitations, and unresolved risks.

If any required check is missing or failing, report the actual incomplete state.
