---
activation: always
---

# Pull Request Rules

**A PR is a release.** Each PR means a build, a version bump and a rollout, so batch the work: finish it, test it and fix it locally, then open one PR per repository for the batch.

- **One open PR per repository.** Before opening a PR, check `mise exec -- gh pr list` for your own open PR in that repository; if one is open and unmerged, push to its branch and update its description instead of opening another. Another person's or session's open PR does not block yours; whichever merges second merges or rebases onto the default branch and takes the next version.
- **Several repositories, one release:** give the PR titles a common prefix so they read as one release (e.g. `vehicle-lists: …` in each repository).
- **Check the PR is still open before pushing to it.** If it has been merged, start a new branch from the freshly fetched default branch.

## Before opening a PR

1. **Work in a git worktree until the PR.** Create a separate worktree and feature branch from the freshly fetched default branch (`git fetch`, then `git worktree add <path> -b <branch> origin/<default-branch>`), and build, test and review there. Never work in the main checkout: it may hold someone else's changes or run their dev servers. Keep one worktree per batch of work, merge the default branch into it when it moves, and remove the worktree once the PR has merged.
2. **Build and test locally first.** Run the full test suites (every database collation CI runs), the formatter check and a warnings-as-errors compile. A failure that also fails on the default branch must be shown failing there, not assumed.
3. **Test user-facing changes end to end in a browser, locally.** Run the local e2e rig with a scenario for every user-facing change, and record what passed. Prove each key check can fail once (invert it, see it fail, restore it).
4. **Review until clean, before the PR opens.** Start a fresh review subagent and tell it to use the repository's review skill (plus `/code-review` and `/security-review`) on the full diff against the default branch.
   - **Fix every finding,** nits included. A finding is only left unfixed when the user decides so.
   - Start a **new** review subagent after the fixes, and repeat the cycle until a round comes back clean.
5. **Bump the version** using the `release` skill and `version-bump.md`. An adequate bump already in this PR satisfies the rule. Take the number from the PR base at the time you open it, not from when the work started.

## Opening the PR

Open with mise-managed gh. Resolve the actual default branch, push the feature branch, and write the exact description to a body file:

```bash
mise exec -- gh pr create --title "type: short description" --body-file /tmp/pr-body.md --base <default-branch> --head <branch>
```

Describe the final change, migrations, rollout steps, and the checks actually run (suites, e2e scenarios, review rounds). Update the existing PR when continuing the same work.

## Reviews on the PR

Every review round is recorded on the PR:

1. Post the **full review** as a PR comment.
2. Address **every** finding and fix them all.
3. Post a second comment listing **each finding and how it was fixed** (commit SHAs).
4. Ask a **fresh** review subagent for another round, and repeat until a round is clean. CI failures follow the same cycle.

The pre-PR review rounds are posted on the PR when it opens, so the whole history is visible.

**Merging is a human task. Never merge, squash-merge, or push directly to the default branch. No exceptions.** Creating branches, pushing feature branches, and creating PRs are allowed. When ready, ask the user to merge.
