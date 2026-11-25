---
name: pull-requests
description: This machine's specifics for pull requests on top of compound-v:pull-requests — gh through mise as the factory GitHub App, the second voice (Astra through Codex, or Claude Fable from Codex), recording a goal's PR for the merge poller, updating plugin installs on both machines, and Codex hook trust. Use when opening a PR, running a review round's second voice, or after a plugin PR merges.
---

# Pull requests: this machine's specifics

The procedure is `compound-v:pull-requests`, the bump `compound-v:release` and the reviews `compound-v:review-loop`. On this machine:

- **gh always goes through mise:** `mise exec -- gh …`. In a worktree whose `mise.toml` isn't trusted, mise refuses to start: run `mise trust <worktree>/mise.toml` first, or run from outside. When watching checks right after a push, put `sleep 30 &&` before `mise exec -- gh pr checks <n> -R <owner>/<repo> --watch --interval 30` in the same background command, because GitHub needs a moment to register the runs.
- **You act as the factory GitHub App, `mapleset-forge[bot]`.** `gh` (through mise or not) reaches oh's wrapper, which picks the App's short-lived token for the repo's owner from `-R`, a URL, an API path, a search qualifier or the current repo's `origin`; git's credential helper does the same from the URL. A caller that knows the owner but can't name it in the arguments sets `FORGE_OWNER=<owner>`. Your PRs are authored by the App, so the user can review and approve them. A token error names the minting timer: say so and stop, never work around it.
- **Never use the user's own credentials:** their `gh` login (`gh auth login`/`switch`/`token` for their account, an unset `GH_TOKEN` to reach the keyring), `~/.kube/admin.yaml`, their gcloud login, or their browser through Claude-in-Chrome on github.com, even when it would get you past a block. A step that needs them is a task for the user, with the command written for their credentials (`KUBECONFIG=~/.kube/admin.yaml KUBE_CONTEXT=ny1 …` for admin kubectl).
- **Watching checks from Codex:** nothing wakes the session when a background watch ends; read its output before saying anything is green.
- **Reading a PR's state:** `mise exec -- gh pr view <n> -R <owner>/<repo> --json state,isDraft,baseRefName,mergeable,mergeStateStatus,statusCheckRollup`. `CONFLICTING`/`DIRTY` means merge the default branch in; `BLOCKED`/`UNSTABLE` means a check is red; `UNKNOWN` means not computed yet, so look again; `BEHIND` appears only where branch rules require up-to-date branches. Back to draft with `mise exec -- gh pr ready <n> --undo -R <owner>/<repo>`; retarget a stacked PR with `mise exec -- gh pr edit <n> --base <default-branch> -R <owner>/<repo>`.

## The second voice (Astra)

Wherever the review loop calls for a second voice, and for any "Astra" review the user asks for, run Astra high through Codex in the background, with the brief on stdin:

```bash
mise exec -- codex exec -m gpt-6-astra -c model_reasoning_effort=high -c web_search="live" -s read-only --skip-git-repo-check -C <dir> -o <out.md> - < brief.md
```

Tell Astra which skill to use (`compound-v:review`, `compound-v:followup` or `compound-v:plan-review`), the diff range or plan, a finding-ID prefix, and the facts already verified. Paste in what its sandbox can't reach (private issues, and anything from the user's board or logs). It can't post or call MCP tools, so post its report yourself, unchanged, under an "Astra high (Codex)" header. Don't add `--dangerously-bypass-hook-trust`. If Codex fails or is unavailable, fall back as the review loop says and note it on the PR.

When you are the Codex session, a fresh reviewer is a separate background `codex exec` with the brief on stdin, and the second voice is Claude with web access: `claude -p --model fable --allowedTools "WebSearch,WebFetch" < brief.md`.

## After a plugin PR merges

- **Update every install:** `claude plugin marketplace update <marketplace>` and `claude plugin update <plugin>@<marketplace>`, then `codex plugin marketplace upgrade <marketplace>` and `codex plugin add <plugin>@<marketplace>` (the upgrade alone doesn't fetch a plugin changed only in its own repository). Do it here and, over ssh, on every other session host by its alias (each host's `~/.ssh/config` names the others by Tailscale IP); list any host you can't reach, and confirm the versions.
- **Codex hook trust:** after every plugin update, or when a plugin's ID changes (a new marketplace or name), Codex no longer trusts the plugin's hooks, and `codex exec` skips untrusted hooks without a word. Ask the user to open Codex once on each machine and trust them ("Hooks need review" → trust, or `/hooks`). Then confirm a new Codex session's log carries the plugin's always-on text, and that each oh guard refuses one harmless test command (`pkill -f no-such-test`, `kubeseal --version`, `git push --force` in a scratch repository).
