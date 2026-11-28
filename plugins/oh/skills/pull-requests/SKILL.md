---
name: pull-requests
description: This machine's specifics for pull requests on top of compound-v:pull-requests — gh through mise as the Sugarhouse App, merging your own PR into `rc`, the second voice (Astra through Codex, or Claude Fable from Codex), plugin installs and Codex hook trust. Use when opening or merging a PR, running a review round's second voice, or after a plugin PR or release merges.
---

# Pull requests: this machine's specifics

The procedure is `compound-v:pull-requests`, the bump `compound-v:release` and the reviews `compound-v:review-loop`. On this machine:

- **gh goes through mise:** `mise exec -- gh …`, which acts as the Sugarhouse GitHub App; `sugar gh --as-owner …` acts as the user and needs their permission first. In a worktree whose `mise.toml` isn't trusted, mise refuses to start: run `mise trust <worktree>/mise.toml` first, or run from outside. When watching checks right after a push, put `sleep 30 &&` before `mise exec -- gh pr checks <n> -R <owner>/<repo> --watch --interval 30` in the same background command, because GitHub needs a moment to register the runs.
- **Watching checks from Codex:** nothing wakes the session when a background watch ends; read its output before saying anything is green.
- **Reading a PR's state:** `mise exec -- gh pr view <n> -R <owner>/<repo> --json state,isDraft,baseRefName,mergeable,mergeStateStatus,statusCheckRollup`. `CONFLICTING`/`DIRTY` means merge the base branch in (`rc` in a repository Sugarhouse has set up); `BLOCKED`/`UNSTABLE` means a check is red; `UNKNOWN` means not computed yet, so look again; `BEHIND` appears only where branch rules require up-to-date branches. Back to draft with `mise exec -- gh pr ready <n> --undo -R <owner>/<repo>`; retarget a stacked PR with `mise exec -- gh pr edit <n> --base <base-branch> -R <owner>/<repo>`.
- **Merging into `rc` or `hotfix`** (a repository Sugarhouse has set up): once the review loop's last round has no must-fix findings and the PR is up to date and green, merge it yourself: `mise exec -- gh pr merge <full PR URL> --squash`. Then clean up as `compound-v:pull-requests` says. No merge task, and no install update: those come with the release.

## The second voice (Astra)

Wherever the review loop calls for a second voice, and for any "Astra" review the user asks for, run Astra high through Codex in the background, with the brief on stdin:

```bash
mise exec -- codex exec -m gpt-6-astra -c model_reasoning_effort=high -c web_search="live" -s read-only --skip-git-repo-check -C <dir> -o <out.md> - < brief.md
```

Tell Astra which skill to use (`compound-v:review`, `compound-v:followup` or `compound-v:plan-review`), the diff range or plan, a finding-ID prefix, and the facts already verified. Paste in what its sandbox can't reach (private issues, and anything from the user's board or logs). It can't post or call MCP tools, so post its report yourself, unchanged, under an "Astra high (Codex)" header. Don't add `--dangerously-bypass-hook-trust`. If Codex fails or is unavailable, fall back as the review loop says and note it on the PR.

When you are the Codex session, a fresh reviewer is a separate background `codex exec` with the brief on stdin, and the second voice is Claude with web access: `claude -p --model fable --allowedTools "WebSearch,WebFetch" < brief.md`.

## After a plugin PR or release merges

- **Where Sugarhouse has set the repository up,** a merge into `rc` changes no install. When the user merges the release (`sugar release`), Sugarhouse installs it on both machines and asks for the Codex re-trust below if hooks changed; check `sugar release status` reaches done.
- **Elsewhere, update every install** after the merge: `claude plugin marketplace update <marketplace>` and `claude plugin update <plugin>@<marketplace>`, then `codex plugin marketplace upgrade <marketplace>` and `codex plugin add <plugin>@<marketplace>` (the upgrade alone doesn't fetch a plugin changed only in its own repository). Do it here and, over ssh, on every other session host by its alias (each host's `~/.ssh/config` names the others by Tailscale IP); list any host you can't reach, and confirm the versions.
- **Stale Codex entries:** `codex plugin list` hides a plugin its marketplace no longer lists, while its `[plugins."<plugin>@<marketplace>"]` entry in `~/.codex/config.toml` can stay `enabled = true` and keep loading it (an old copy then runs its hooks twice). On each machine, list the entries (`grep -A1 '^\[plugins\.' ~/.codex/config.toml`, which prints only the plugin tables): any entry not `enabled = false` that `codex plugin list` doesn't show is stale (a table with no `enabled` key follows `plugins._default`); remove it with `codex plugin remove`.
- **Codex hook trust:** after every plugin install that changed it (once per release), or when a plugin's ID changes (a new marketplace or name), Codex no longer trusts the plugin's hooks, and `codex exec` skips untrusted hooks without a word. Ask the user to open Codex once on each machine and trust them ("Hooks need review" → trust, or `/hooks`). Then confirm a new Codex session's log carries the plugin's always-on text, and that each oh guard catches one harmless test command (`pkill -f no-such-test`, `kubeseal --version`, `kubectl --context no-such-context delete ns no-such-test`, which asks).
