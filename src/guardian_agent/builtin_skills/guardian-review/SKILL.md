---
name: guardian-review
description: "Review completed implementation in two independent stages: specification compliance first, then code quality, security, maintainability, and test adequacy. Use before final verification, commits, pull requests, or releases."
---

# Guardian Review

## Stage 1: Specification

Compare the diff and behavior with every confirmed requirement and exclusion. Report missing, extra, or contradictory behavior. Do not begin quality review until specification findings are resolved or explicitly accepted.

## Stage 2: Quality

Inspect correctness, security, error handling, maintainability, compatibility, tests, and rollback. Rank findings as blocking, important, or advisory. Cite files and concrete evidence.

Never treat a worker's self-review as independent approval.
