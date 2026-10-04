---
activation: always
---

# Pull Request Rules

**A PR is a release.** Each PR means a build, a version bump and a rollout, so batch the work: finish it, test it and fix it locally, then open one PR per repository for the batch.

- **One open PR per repository for your work.** Your PR is the one whose branch you (this session or this batch of work) created. Before opening a PR, check `mise exec -- gh pr list --state open`; if your PR is open and unmerged, push to its branch and update its description instead of opening another. Another person's or session's open PR (same GitHub account or not) does not block yours; whichever merges second merges or rebases onto the default branch and takes the next version (`version-bump.md`).
- **Several repositories, one release:** give the PR titles a common prefix so they read as one release (e.g. `vehicle-lists: …` in each repository).
- **Check the PR is still open before pushing to it.** If it has been merged, start a new branch and worktree from the freshly fetched default branch.

## Before opening a PR

1. **Work in a git worktree until the PR.** For new work, create a separate worktree and feature branch from the freshly fetched default branch (`git fetch`, then `git worktree add <path> -b <branch> origin/<default-branch>`). To continue your open PR, add a worktree on that PR's branch instead (`git worktree add <path> <branch>`). Build, test and review there. Never work in the main checkout: it may hold someone else's changes or run their dev servers. Keep one worktree per batch of work, merge the default branch into it when it moves, and remove the worktree once the PR has merged.
2. **Build and test locally first.** Run the full test suites the way CI runs them (every configuration CI covers, such as each database or locale variant), the formatter check and a warnings-as-errors compile where the language has one. A failure that also fails on the default branch must be shown failing there, not assumed.
3. **Check user-facing changes end to end, locally.** When the repository has a local end-to-end setup (for example a browser test rig), run a scenario for every user-facing change and record what passed. For each key check, show once that it can fail: break the condition it checks (or invert the assertion), see it fail, then restore it. When the repository has no end-to-end setup, say so in the PR and describe the manual check you ran instead.
4. **Review until clean, before the PR opens.** Start a fresh review subagent (or, where the host has no subagents, a fresh review pass) and tell it to use the repository's review skill, plus the host's code-review and security-review commands where they exist (`/code-review`, `/security-review`), on the full diff against the default branch.
   - **Fix every valid finding,** nits included. A finding may be refuted with evidence (cite the code or a test showing it is wrong); only the user may waive a valid finding.
   - Start a **new** reviewer after the fixes, and repeat the cycle until a round comes back clean.
5. **Bump the version last,** using the `release` skill and `version-bump.md`, once the work is tested and reviewed. An adequate bump already in this PR satisfies the rule. Take the number from the PR base at the time you open it, not from when the work started.

## Opening the PR

Open with mise-managed gh. Resolve the actual default branch, push the feature branch, and write the exact description to a body file of your own (a unique path, so concurrent sessions don't overwrite each other):

```bash
body=$(mktemp -t pr-body)
# write the description to "$body", then:
mise exec -- gh pr create --title "type: short description" --body-file "$body" --base <default-branch> --head <branch>
```

Describe the final change, migrations, rollout steps, and the checks actually run (suites, end-to-end scenarios, review rounds). Update the existing PR when continuing the same work.

## Reviews on the PR

Every review round is recorded on the PR, including the rounds run before it opened (post them when it opens):

1. Post the **full review** as a PR comment.
2. Address **every** finding: fix it, or refute it with evidence.
3. Post a second comment listing **each finding and what was done** (the fix and its commit SHA, or the evidence).
4. After every push of new commits (fixes, CI fixes, merges of the default branch), ask a **fresh** reviewer for another round, and repeat until a round is clean.

**Merging is a human task. Never merge, squash-merge, or push directly to the default branch. No exceptions.** Creating branches, pushing feature branches, and creating PRs are allowed. When ready, ask the user to merge.
