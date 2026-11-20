---
name: pull-requests
description: Step-by-step procedure for preparing, opening and updating a pull request where every PR is a release - worktree setup, local tests and end-to-end checks, the review loop, the version bump, gh pr create, what goes in the PR description, and keeping it mergeable and green until it merges. Use before opening a PR, when pushing more commits to an open PR, when a PR has conflicts or failing checks, before saying a PR is ready to merge, when running or posting a review round (including the second-voice Astra review of a PR or plan), after a PR merges, or when the user asks to ship, open or update a PR.
---

# Pull request procedure

The always-on *Pull requests* and *Production guard* sections of the `oh` hook set the policy: a PR is a release, one PR per repository, worktrees until the PR, local tests, fresh reviewers until no must-fix findings remain, reviews posted on the PR, and the user merges. This is the procedure behind it.

## Which PR is yours

- Your PR is the one whose branch you (this session or this batch of work) created. In a new session, treat a PR as yours when the user points you to it or its branch is the one you are continuing; otherwise ask once.
- Before opening a PR, run `mise exec -- gh pr list --state open`. If your PR is open and unmerged, push to its branch and update its description instead of opening another.
- Another person's or session's open PR (same GitHub account or not) does not block yours. Whichever merges second merges the default branch into its own branch (no rebase or force-push, so posted commit SHAs stay valid) and takes the next version (step 5 of *Before opening a PR*).
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
4. **Open a draft, then review.** Once local tests pass, open the PR as a draft (*Opening the PR*), so each review round is posted on it as it lands. Run `compound-v:review-loop` on the full diff against the default branch, at the tier it picks; the tiers and their rounds are defined there. Keep the decisions table from the plan (or start one) in the PR body or a file the reviewers read. Before opening, remove any debug output, temporary logging and stray TODOs you added. Mark the PR ready (`mise exec -- gh pr ready <n>`) only when the user could merge it right now: the loop's final round has no must-fix findings, the bump has landed, its base is the default branch, and it is mergeable, up to date and green (*Keeping it mergeable and green*).
5. **Bump the version last,** using the `oh:release` skill, once the work is tested and reviewed. Every PR in a repository with a plugin manifest, `mix.exs`, `go.mod` or `Cargo.toml` carries a bump, even where CI doesn't check; where a repository holds several plugins, a PR that touches none bumps nothing. An adequate bump already in this PR satisfies it. Take the number from the PR base when you bump, not from when the work started. If another PR merges first and the base reaches or passes your version, re-apply the same bump level to the base's version (a minor PR stays a minor bump).

## Opening the PR

Open with mise-managed gh. Resolve the actual default branch, push the feature branch, and write the exact description to a body file of your own (a unique path, so concurrent sessions don't overwrite each other):

```bash
body=$(mktemp "${TMPDIR:-/tmp}/pr-body.XXXXXX")
# write the description to "$body", then:
mise exec -- gh pr create --draft --title "<prefix>: short description" --body-file "$body" --base <default-branch> --head <branch>
```

Describe the final change, migrations and rollout steps, and report the checks you actually ran with their exact commands and results (suites, end-to-end scenarios, review rounds), not a summary like "tests pass". Update the existing PR when continuing the same work.

## Keeping it mergeable and green

Until the user merges it, the PR's state is yours to watch:

- **After every push**, watch the checks in the background: `mise exec -- gh pr checks <n> -R <owner>/<repo> --watch --interval 30` (in a worktree whose `mise.toml` isn't trusted, mise refuses to start: run `mise trust <worktree>/mise.toml` first, or run it from outside). Started within seconds of a push it can exit 1 with `no checks reported`: that's GitHub not having registered the runs yet, not "no CI", so put `sleep 30 &&` in front of it in the same background command. Fix what fails, push, watch again. A check that's red by design (Version Bump Check on a draft before the bump lands last) waits for the bump; everything else gets fixed. Don't report a PR as ready while a check is red or still running. In Codex the watch keeps running after the call returns but nothing wakes you when it ends: read its output before saying anything is green.
- **Before saying anything is ready to merge**, and when you come back to a session with open PRs, look at each: `mise exec -- gh pr view <n> -R <owner>/<repo> --json state,isDraft,baseRefName,mergeable,mergeStateStatus,statusCheckRollup`. A `baseRefName` other than the default branch means the PR stays a draft (*Ready means mergeable now*). `mergeable: CONFLICTING` or `DIRTY` means merge the default branch in now; `BLOCKED` or `UNSTABLE` means a check is red, so read `statusCheckRollup`; `UNKNOWN` means GitHub hasn't computed it yet, so check again shortly rather than assuming it's fine. `BEHIND` only appears where the branch rules require up-to-date branches; elsewhere `git fetch` and `git log --oneline HEAD..origin/<default>` tell you the base moved. Checks don't rerun when the base moves, so a green rollup on a branch that's behind can be stale.
- **When the base moves** (another PR merged), merge the default branch into your branch (no rebase or force-push), resolve conflicts, re-apply your version bump at the same level on top of the base's new version, run the affected checks locally, push, and watch CI again. Two PRs that set the same version line merge without a conflict and still fail the version check, so re-bump even when git reports none.
- **Ready means mergeable now.** When a ready PR stops qualifying (the base moved, or a check went red), put it back to draft with `mise exec -- gh pr ready <n> --undo -R <owner>/<repo>` before you fix it, and mark it ready again once it is up to date and green. A PR whose base is another PR's branch stays a draft: after that PR merges, retarget yours (`mise exec -- gh pr edit <n> --base <default-branch> -R <owner>/<repo>`), merge the default branch in, re-bump, watch CI, and only then mark it ready. Merging into a stacked base lands the work on that branch, not the default: GitHub retargets a stacked PR when its base branch is deleted, but not always before someone merges it; one merged into a stale base needs a new PR from that branch to carry it over.
- **A failure that isn't yours** (flaky, or failing on the default branch too) is shown failing on the default branch, with the run link, before you say so. Fix flakiness rather than re-running until green; for an infrastructure outage you can't reproduce, link the run, say so on the PR, then re-run.
- Tell the user what you found and fixed; a list of "ready to merge" PRs only includes ones that are open, non-draft, based on the default branch, up to date, mergeable and green. When several are ready at once, give the merge order: when the first merges, every one after it is behind and goes back to draft until it has merged the default branch in and is green again.

## Reviews on the PR

`compound-v:review-loop` records every round on the PR: each review as a comment, then a fix-notes comment answering each finding by ID with the fix's commit SHA or the evidence. A round that ran before the PR existed is posted when it opens. If you have no GitHub access from this host, put the reviews and the finding-by-finding outcome in your report to the user instead, and say they aren't on the PR yet.

**The second voice (Astra).** Wherever the review loop calls for one, and for any "Astra" review the user asks for, run Astra high through Codex in the background with the brief on stdin:

```bash
codex exec -m gpt-6-astra -c model_reasoning_effort=high -c web_search="live" -s read-only --skip-git-repo-check -C <dir> -o <out.md> - < brief.md
```

Tell Astra which skill to use (`compound-v:review`, `compound-v:followup` or `compound-v:plan-review`), the diff range or plan, a finding-ID prefix, and the facts already verified; paste in what its sandbox can't reach (private issues, the rough-edge log). Its sandbox can't post or call MCP tools, so post its report on the PR or issue yourself, unchanged, under an "Astra high (Codex)" header. Don't add `--dangerously-bypass-hook-trust`. If Codex fails or is unavailable, fall back as the review loop says and note it on the PR.

When you are the Codex session: a fresh reviewer is a separate background `codex exec` with the brief on stdin, and the second voice is Claude, with web access so it can check current practice: `claude -p --model fable --allowedTools "WebSearch,WebFetch" < brief.md`. Without Claude installed, fall back as the review loop says.

## Merging

Merging is the user's step, because each merge starts a release. Creating branches, pushing feature branches and creating or updating PRs are yours. Don't merge or squash-merge a PR and don't push to the default branch; when the PR is ready, ask the user to merge.

## After the merge

Clean up yourself; don't tell the user "you can delete":
- Confirm the branch is contained in the default branch, then delete it locally and on the remote (if the repository doesn't auto-delete), and remove its worktree and any review clones or scratch build trees. Move out anything still in use first. Never delete the default branch.
- Close the issues the PR finished (plans, research requests, follow-up items) with a short comment linking the PR or merge commit; `Closes #N` covers some, so check what it missed. Say which related issues stay open and why.
- For a plugin, update every install: `claude plugin marketplace update <marketplace>` and `claude plugin update <plugin>@<marketplace>`, then `codex plugin marketplace upgrade <marketplace>` and `codex plugin add <plugin>@<marketplace>` (the upgrade alone doesn't fetch a plugin changed only in its own repository). Do this on this machine and, over ssh, on every other session host by its alias (each host's `~/.ssh/config` names the others by Tailscale IP); list any host you can't reach. Confirm the versions.
