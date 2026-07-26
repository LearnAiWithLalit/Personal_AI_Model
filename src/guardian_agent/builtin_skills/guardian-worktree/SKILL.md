---
name: guardian-worktree
description: Create an isolated git worktree and clean baseline before complex, risky, delegated, or parallel implementation. Use when changes should not modify the user's active branch directly.
---

# Guardian Worktree

1. Confirm the repository and active branch.
2. Refuse to overwrite an existing worktree path or branch.
3. Create a new bounded worktree and record its branch and path.
4. Run the baseline verification before changes.
5. Keep delegated work inside the worktree.
6. Preview the diff and verify before merge or pull request.
7. Remove the worktree only through an explicit cleanup or rollback request.
