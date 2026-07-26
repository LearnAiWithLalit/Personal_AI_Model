---
name: guardian-debug
description: Diagnose bugs, failing tests, performance regressions, integration failures, and unexpected behavior through evidence and root-cause analysis before editing code.
---

# Guardian Debug

1. Capture the exact symptom, environment, error, and reproduction steps.
2. Reproduce consistently or state what evidence is still missing.
3. Inspect recent changes and trace data across component boundaries.
4. Compare with a similar working path.
5. Record one falsifiable root-cause hypothesis.
6. Test one variable with the smallest diagnostic change.
7. Add a failing regression test, fix the source, and verify.

After three failed fix attempts, stop and require architecture review instead of stacking another guess.
