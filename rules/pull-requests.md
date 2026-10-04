---
activation: always
---

# Pull requests

Here a PR is a release: a build, a version bump and a rollout. Batch the work, finish and test it locally, then open one PR per repository. To open or update a PR, or run a review round, use the `pull-requests` skill.

- One open PR per repository for your work: while yours is open, push to its branch (check it is still open first) instead of opening another. Others' open PRs don't block yours.
- Until the PR, make changes in a separate git worktree on a feature branch; the main checkout may hold someone else's work or dev servers. Reading code or running a requested command there is fine.
- Run the tests the way CI does, and check user-facing changes end to end, locally first, so the PR starts green.
- Before the PR opens, a fresh review subagent reviews the full diff (where the host has no subagents, a fresh full-diff review pass). Findings are must-fix or polish. Only must-fix findings earn another fresh round; the first round with none ends the loop: fix its polish in one pass, check that diff, and stop. If three full rounds still find must-fix issues, stop and bring the recurring problem to the user. A fresh reviewer has no stake in the code.
- Post each review round, and what was done about each finding, on the PR, so the release can be audited from the PR.
- The user merges, because each merge starts a release: don't merge a PR or push to the default branch. Merge the default branch into your feature branch when it moves; don't rebase or force-push, so SHAs posted on the PR stay valid.
