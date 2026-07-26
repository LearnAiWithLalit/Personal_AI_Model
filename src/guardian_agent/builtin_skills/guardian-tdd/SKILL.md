---
name: guardian-tdd
description: Implement behavior using a red-green-refactor cycle with regression evidence. Use for bug fixes, business logic, APIs, parsing, security boundaries, and other behavior that can be tested automatically.
---

# Guardian TDD

1. Write the smallest test that demonstrates the missing or broken behavior.
2. Run it and retain evidence that it fails for the expected reason.
3. Implement the smallest focused change.
4. Run the focused test, then the relevant full suite.
5. Refactor only while tests remain green.
6. Record the red and green commands, exit codes, and affected requirement.

Do not use snapshot-only or assertion-free tests as proof.
