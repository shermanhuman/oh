---
name: pull-requests
description: Step-by-step procedure for preparing, opening and updating a pull request where every PR is a release - worktree setup, local tests and end-to-end checks, review rounds until clean, the version bump, gh pr create, and recording each review round on the PR. Use before opening a PR, when pushing more commits to an open PR, when running or posting a review round, or when the user asks to ship, open or update a PR.
---

# Pull request procedure

The always-on pull-request rule sets the policy: a PR is a release, one PR per repository, worktrees until the PR, local tests, fresh reviewers until clean, reviews posted on the PR, and the user merges. This is the procedure behind it.

## Which PR is yours

- Your PR is the one whose branch you (this session or this batch of work) created. In a new session, treat a PR as yours when the user points you to it or its branch is the one you are continuing; otherwise ask once.
- Before opening a PR, run `mise exec -- gh pr list --state open`. If your PR is open and unmerged, push to its branch and update its description instead of opening another.
- Another person's or session's open PR (same GitHub account or not) does not block yours. Whichever merges second merges the default branch into its own branch (no rebase or force-push, so posted commit SHAs stay valid) and takes the next version under the version-bump rule.
- Check that the PR is still open before each push to it (`mise exec -- gh pr view <number> --json state`). If it has been merged, start a new branch and worktree from the freshly fetched default branch.
- Several repositories, one release: give the PR titles a common prefix so they read as one release (for example `vehicle-lists: …` in each repository). The prefix is the start of the title, in place of a conventional `type:`; a single-repository PR may use `type:` or a topic prefix.

## Before opening a PR

1. **Work in a git worktree until the PR.** For new work, create a separate worktree and feature branch from the freshly fetched default branch:

   ```bash
   git fetch
   git worktree add --no-track -b <branch> <path> origin/<default-branch>
   ```

   `--no-track` keeps the new branch from tracking the default branch, so a later `git push -u origin <branch>` sets the right upstream and status never compares against the default branch. To continue your open PR, add a worktree on that PR's branch instead (`git fetch`, then `git worktree add <path> <branch>`). Build, test and review there. The main checkout may hold someone else's changes or run their dev servers, so don't make PR changes in it; reading code there, or running a command the user asked for, is fine. Keep one worktree per batch of work, merge the default branch into it when it moves (merge, don't rebase), and remove the worktree once the PR has merged.
2. **Build and test locally first.** Run the full test suites the way CI runs them (every configuration CI covers, such as each database or locale variant), the formatter check and a warnings-as-errors compile where the language has one. A failure that also fails on the default branch has to be shown failing there, not assumed.
3. **Check user-facing changes end to end, locally.** When the repository has a local end-to-end setup (for example a browser test rig), run a scenario for every user-facing change and record what passed. For each key check, show once that it can fail: break the condition it checks (or invert the assertion), see it fail, then restore it. A check that has never failed may not be checking anything. When the repository has no end-to-end setup, say so in the PR and describe the manual check you ran instead.
4. **Review until clean, before the PR opens.** Start a fresh review subagent and tell it to use the repository's review skill, plus the host's built-in code-review and security-review commands where it has them (in Claude Code, `/code-review high` and `/security-review`), on the full diff against the default branch. Where the host has no subagents, run a fresh review pass yourself that re-reads the full diff from the start, and say in the PR that you did.
   - Fix every valid finding, nits included. A finding may be refuted with evidence (cite the code or a test showing it is wrong); only the user may waive a valid finding.
   - Start a new reviewer after the fixes, and repeat until a round comes back clean. A reviewer that has already seen the code tends to accept its own earlier conclusions, which is why each round gets a fresh one.
5. **Bump the version last,** using the `release` skill and the version-bump rule, once the work is tested and reviewed. An adequate bump already in this PR satisfies the rule. Take the number from the PR base at the time you open it, not from when the work started. If another PR merges first and the base reaches or passes your version, re-apply the same bump level to the base's version (a minor PR stays a minor bump).

## Opening the PR

Open with mise-managed gh. Resolve the actual default branch, push the feature branch, and write the exact description to a body file of your own (a unique path, so concurrent sessions don't overwrite each other):

```bash
body=$(mktemp "${TMPDIR:-/tmp}/pr-body.XXXXXX")
# write the description to "$body", then:
mise exec -- gh pr create --title "<prefix>: short description" --body-file "$body" --base <default-branch> --head <branch>
```

Describe the final change, migrations, rollout steps, and the checks actually run (suites, end-to-end scenarios, review rounds). Update the existing PR when continuing the same work.

## Reviews on the PR

Every review round is recorded on the PR, including the rounds run before it opened (post them when it opens):

1. Post the **full review** as a PR comment. If you have no GitHub access from this host, put the reviews and the finding-by-finding outcome in your report to the user instead, and say that they are not on the PR yet.
2. Address every finding: fix it, or refute it with evidence.
3. Post a second comment listing each finding and what was done (the fix and its commit SHA, or the evidence).
4. After every push of new commits (fixes, CI fixes, merges of the default branch), ask a fresh reviewer for another round, and repeat until a round is clean. A commit that only changes the version number (the bump, or a re-bump after another PR merged) needs no review round of its own.

## Merging

Merging is the user's step, because each merge starts a release. Creating branches, pushing feature branches and creating or updating PRs are yours. Don't merge or squash-merge a PR and don't push to the default branch; when the PR is ready, ask the user to merge.
