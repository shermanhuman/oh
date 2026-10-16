---
name: pull-requests
description: Step-by-step procedure for preparing, opening and updating a pull request where every PR is a release - worktree setup, local tests and end-to-end checks, the review loop, the version bump, gh pr create, what goes in the PR description, and keeping it mergeable and green until it merges. Use before opening a PR, when pushing more commits to an open PR, when a PR has conflicts or failing checks, before saying a PR is ready to merge, when running or posting a review round, or when the user asks to ship, open or update a PR.
---

# Pull request procedure

The always-on *Pull requests are releases* section of the `oh` hook sets the policy: a PR is a release, one PR per repository, worktrees until the PR, local tests, fresh reviewers until no must-fix findings remain, reviews posted on the PR, and the user merges. This is the procedure behind it.

## Which PR is yours

- Your PR is the one whose branch you (this session or this batch of work) created. In a new session, treat a PR as yours when the user points you to it or its branch is the one you are continuing; otherwise ask once.
- Before opening a PR, run `mise exec -- gh pr list --state open`. If your PR is open and unmerged, push to its branch and update its description instead of opening another.
- Another person's or session's open PR (same GitHub account or not) does not block yours. Whichever merges second merges the default branch into its own branch (no rebase or force-push, so posted commit SHAs stay valid) and takes the next version under the hook's *Version bumps* section.
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
4. **Review before the PR opens.** Run `compound-v:review-loop` on the full diff against the default branch, at the tier it picks (light for prose-only diffs, full for everything else, including agent-instruction files); the rounds for each tier are defined there. Keep the decisions table from the plan (or start one) in the PR body or a file the reviewers read. Before opening, remove any debug output, temporary logging and stray TODOs you added.
5. **Bump the version last,** using the `oh:release` skill and the hook's *Version bumps* section, once the work is tested and reviewed. An adequate bump already in this PR satisfies it. Take the number from the PR base when you bump, not from when the work started. If another PR merges first and the base reaches or passes your version, re-apply the same bump level to the base's version (a minor PR stays a minor bump).

## Opening the PR

Open with mise-managed gh. Resolve the actual default branch, push the feature branch, and write the exact description to a body file of your own (a unique path, so concurrent sessions don't overwrite each other):

```bash
body=$(mktemp "${TMPDIR:-/tmp}/pr-body.XXXXXX")
# write the description to "$body", then:
mise exec -- gh pr create --title "<prefix>: short description" --body-file "$body" --base <default-branch> --head <branch>
```

Describe the final change, migrations and rollout steps, and report the checks you actually ran with their exact commands and results (suites, end-to-end scenarios, review rounds), not a summary like "tests pass". Update the existing PR when continuing the same work.

## Keeping it mergeable and green

Until the user merges it, the PR's state is yours to watch:

- **After every push**, watch the checks in the background: `mise exec -- gh pr checks <n> -R <owner>/<repo> --watch --interval 30` (in a worktree whose `mise.toml` isn't trusted, mise refuses to start: run `mise trust <worktree>/mise.toml` first, or run it from outside). Started within seconds of a push it can exit 1 with `no checks reported`: that's GitHub not having registered the runs yet, not "no CI", so put `sleep 30 &&` in front of it in the same background command. Fix what fails, push, watch again. A check that's red by design (Version Bump Check on a draft before the bump lands last) waits for the bump; everything else gets fixed. Don't report a PR as ready while a check is red or still running. In Codex the watch keeps running after the call returns but nothing wakes you when it ends: read its output before saying anything is green.
- **Before saying anything is ready to merge**, and when you come back to a session with open PRs, look at each: `mise exec -- gh pr view <n> -R <owner>/<repo> --json state,isDraft,mergeable,mergeStateStatus,statusCheckRollup`. `mergeable: CONFLICTING` or `DIRTY` means merge the default branch in now; `BLOCKED` or `UNSTABLE` means a check is red, so read `statusCheckRollup`; `UNKNOWN` means GitHub hasn't computed it yet, so check again shortly rather than assuming it's fine. `BEHIND` only appears where the branch rules require up-to-date branches; elsewhere `git fetch` and `git log --oneline HEAD..origin/<default>` tell you the base moved. Checks don't rerun when the base moves, so a green rollup on a branch that's behind can be stale.
- **When the base moves** (another PR merged), merge the default branch into your branch (no rebase or force-push), resolve conflicts, re-apply your version bump at the same level on top of the base's new version, run the affected checks locally, push, and watch CI again. Two PRs that set the same version line merge without a conflict and still fail the version check, so re-bump even when git reports none.
- **A failure that isn't yours** (flaky, or failing on the default branch too) is shown failing on the default branch, with the run link, before you say so. Fix flakiness rather than re-running until green.
- Tell the user what you found and fixed; a list of "ready to merge" PRs only includes ones that are open, non-draft, mergeable and green.

## Reviews on the PR

`compound-v:review-loop` records every round on the PR: each review as a comment, then a fix-notes comment answering each finding by ID with the fix's commit SHA or the evidence. Rounds run before the PR opened are posted when it opens. If you have no GitHub access from this host, put the reviews and the finding-by-finding outcome in your report to the user instead, and say they aren't on the PR yet.

## Merging

Merging is the user's step, because each merge starts a release. Creating branches, pushing feature branches and creating or updating PRs are yours. Don't merge or squash-merge a PR and don't push to the default branch; when the PR is ready, ask the user to merge.
