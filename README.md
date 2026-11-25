# Oh

My personal Claude Code and Codex plugins: the working agreements I want in every session, plus the stack and API knowledge for the projects I work on.

> [!NOTE]
> This is not a general-purpose library. The plugins are specific to my stack (Phoenix, Telnyx, Tekmetric, …) and my way of shipping. What _is_ useful is the shape: a personal plugin that fills in the choices a generic methodology like [Compound V](https://github.com/shermanhuman/compound-v) leaves open, and per-project plugins that only switch on where they apply.

Named after [Sadaharu Oh](https://en.wikipedia.org/wiki/Sadaharu_Oh) — the greatest home run hitter in professional baseball history. 868 career home runs across 22 seasons with the Yomiuri Giants. If Compound V gives your agent superpowers, Oh is the discipline and consistency that turns raw power into a record-breaking career. 王貞治.

## Plugins

| Plugin | What it holds | Where it's on |
|---|---|---|
| `oh` | The always-on working agreements below, and the skills `pull-requests` (this machine's specifics behind compound-v's procedure), `release`, `mise`, `waxseal` and `dockerfile`. The factory's rules (goals, the board, keep-going, rough edges) moved to the `sugarhouse` plugin, which ships with each Sugarhouse release (`sugar install-plugin`) | everywhere |
| `oh-phoenix` | `phoenix` (LiveView, Ecto, migrations, architecture and testing references), `daisyui` | Elixir repositories |
| `oh-tekmetric` | `tekmetric-api` with the full endpoint catalog | repositories that sync Tekmetric |
| `oh-telnyx` | `telnyx-call-control` | voice/SMS repositories |
| `oh-postmark` | `postmark-api` | repositories that send email |
| `oh-groq` | `groq-api` (Whisper transcription) | repositories that transcribe |

## How I work on top of Compound V

Compound V's [workflow](https://github.com/shermanhuman/compound-v#the-workflow) is the frame: pick, plan, review the plan, interrogate, build in a worktree, run the review loop, merge, file follow-ups. Oh adds my choices and the reasons for them:

- **Mise first.** Every tool comes from mise, and runs through `mise exec` when the shell isn't activated, so nothing gets installed twice in different ways.
- **A pull request is a release.** I keep one open PR per repository, batch the work, and test it locally before it opens. PRs stay drafts until I could merge them right now: last review round clean, based on the default branch, up to date, mergeable and green. A PR that stops meeting that goes back to draft. I merge.
- **Worktrees, always.** My main checkouts run dev servers and sometimes hold another session's branch.
- **Watch your own PRs.** After every push, the agent watches CI and mergeability, because I kept being the one who found the red check or the conflict.
- **A version bump in every PR, done last.** It's re-applied when the base moves, because two PRs that set the same version line merge cleanly and then fail CI.
- **Sealed secrets only through waxseal**, one visible command per call, with a guard hook that refuses `kubeseal`, `gcloud secrets` changes and value reads, and Secret Manager URLs (details in the `oh:waxseal` skill and the hook text).
- **A production guard instead of a sandbox.** I run Claude Code with `--dangerously-skip-permissions` so it never stops to ask while coding. A guard hook refuses what is always mine (merging, pushing to a default branch, force-pushing, deleting a repository) and asks me before irreversible production actions (deletes, drains and scale-to-zero on a non-local cluster, `helm uninstall`, destructive SQL on a remote database). Deleting cloud resources outside a cluster waits for me too, by rule only. The release routine (a GitOps repository's stage and promote PRs, or restarts, Argo refreshes, migration Jobs and deploy scripts) goes ahead without asking, except a destructive change inside it, which waits for me.
- **Reviewers:** Fable at high effort for rounds that review the whole diff and a plan's first review, Opus high for follow-ups and plan re-reviews, and Astra high through `codex exec` as the second voice.
- **`/next` without the prefix.** A one-line personal skill at `~/.claude/skills/next/SKILL.md` ("Use the `compound-v:next` skill with: $ARGUMENTS") lets me type `/next` instead of `/compound-v:next` in Claude Code. A plugin can't add a bare command, so it lives only on my machine; in Codex it's still `$compound-v:next`.

## Install

The plugins are listed in this repository's own marketplace, `mapleset` (the repository is private, so installing needs read access: with the `shermanhuman/oh` form, an SSH key GitHub accepts, or else `gh auth login` plus `gh auth setup-git` for HTTPS). `oh` builds on Compound V, so install that too.

Claude Code:

```bash
claude plugin marketplace add shermanhuman/compound-v
claude plugin install compound-v@compound-v
claude plugin marketplace add shermanhuman/oh
claude plugin install oh@mapleset
claude plugin install oh-phoenix@mapleset
```

Codex:

```bash
codex plugin marketplace add shermanhuman/compound-v
codex plugin add compound-v@compound-v
codex plugin marketplace add shermanhuman/oh
codex plugin add oh@mapleset
codex plugin add oh-phoenix@mapleset
```

Moving from the old `@compound-v` installs: uninstall each one (`claude plugin uninstall oh@compound-v`, `codex plugin remove oh@compound-v`, and the same for any `oh-*`) before installing `@mapleset`, so a plugin isn't loaded twice. Repositories that enable `oh-*@compound-v` in a committed `.claude/settings.json` or `.codex/config.toml` (breakdown-admin, breakdown-rosearch, breakdown-sales, breakdown-sites, supportcannon) switch to `oh-*@mapleset` and declare the `mapleset` marketplace before Compound V stops listing the oh plugins.

Install the other `oh-*` plugins the same way. Start a new Claude Code session (or run `/reload-plugins`). In Codex, open `/hooks` and trust oh's four hooks (the session-start rules and the waxseal, production, and process and secrets guards) and Compound V's, again after every update, since Codex ties trust to every file in the plugin, and when the plugin's ID changes. Trust is per hook definition, so an update that changes `hooks.json` asks again. To update: in Claude Code, `claude plugin marketplace update mapleset` and `claude plugin update oh@mapleset`; in Codex, `codex plugin marketplace upgrade mapleset` and `codex plugin add oh@mapleset`.

## Stack and API plugins per repository

The `oh-*` plugins are installed once at user scope, switched off in user settings and switched on in each repository that needs them, as [Compound V describes](https://github.com/shermanhuman/compound-v#switching-a-plugin-on-per-repository). Codex reads a repository's `.codex/config.toml` only once that project path is trusted: trust each main checkout once, and its worktrees follow.

## Gotchas

- **The process and secrets guard reads shell commands only.** It doesn't see the Read tool, interpreter code, commands run on another machine over ssh, a file reached through `cd dir && cat name` when only the directory marks it secret, globs (`cat .env*`), text inside a double-quoted `"$(…)"`, a script written by heredoc and then run, PIDs passed through a file (`ps … | grep … > pids; for p in $(cat pids); do kill $p; done`), lookups in process substitution (`done < <(pgrep …)`) or in a `{ …; }` group piped to `xargs kill`. The always-on rule covers those.
- **Astra can't post.** It runs `codex exec -s read-only`, so it can't post comments or call MCP tools. Post its report yourself, unchanged, under an "Astra high (Codex)" header.
- **`codex exec` skips hooks you haven't trusted**, and Astra runs don't use `--dangerously-bypass-hook-trust`, so review briefs carry the rules they need.
- **Codex's question tool works in Plan mode only by default.** To allow it in Default mode, run `codex features enable default_mode_request_user_input` (still marked under development in Codex 0.162.1).
- **The guards are backstops, not sandboxes.** They check only what a shell would execute, fail open on input they can't handle, and need `python3`.
- **The production guard can't see everything.** A port-forwarded production database looks like localhost, one named by a `pg_service.conf` entry isn't resolved, commands inside a double-quoted command substitution (`"$(...)"` or backticks) aren't read, and neither is a heredoc inside a quoted command string (`ssh vm 'psql <<EOF …'`); a kube context or database host named only in a variable set outside the command is treated as production and asks; interpreter code isn't read. The always-on rule covers those.
- **Codex can't ask from a hook.** It logs an `ask` as a failed hook and runs the command, so in Codex the production guard refuses the cases it would ask about in Claude Code, and the agent hands you the command.
- **After `codex plugin add oh-<name>@mapleset`**, that plugin's `enabled = true` comes back in `~/.codex/config.toml`. Switch it off again for your user.
- **Cloud sessions load no plugins**, so each repository's `AGENTS.md` repeats the rules that must always hold: I merge, a PR is a release, every PR bumps the version.
- **Any `mise exec` in a worktree with an untrusted `mise.toml` fails**, including `mise exec -- gh pr checks --watch`. Run `mise trust <worktree>/mise.toml` first, or run it from a directory without one.

## Upgrading from 1.x

1.x was a [Promptherder](https://github.com/shermanhuman/promptherder) herd. In each repository that pulled it, follow [Compound V's upgrade notes](https://github.com/shermanhuman/compound-v/blob/main/docs/upgrading-from-1x.md) with the `oh` herd in place of `compound-v`: remove `.promptherder/herds/oh` (and its `lock.json` entry) before the re-sync, and in the final check also look for the old copies of oh's skills (`mise`, `pull-requests`, `release`, `waxseal`, `dockerfile`, `phoenix`, `daisyui`, `tekmetric-api`, `telnyx-call-control`, `postmark-api`, `groq-api`, `promptherder`) under `.claude/skills/` and `.agents/skills/`. Then install the plugins as above and switch the stack and API plugins on per repository.

## License

MIT License — Copyright (c) 2026 Sherman Boyd

## Changelog

- oh 3.0.0: the factory's rules move to the `sugarhouse` plugin, which ships with each Sugarhouse release ([Applesauce-Labs/sugarhouse#12](https://github.com/Applesauce-Labs/sugarhouse/issues/12)): the *Goals*, *Questions and plans go to Sugarhouse* and *Rough edges* sections, the `goals` and `rough-edges` skills (now `sugarhouse:goals` and `sugarhouse:rough-edges`), the keep-going Stop hook (now `sugar hook stop`, with the same log and off switch), the `sugarhouse` MCP server, and the `goal.prs` and plan-link lines in `pull-requests`. Install the sugarhouse plugin first (`sugar install-plugin`), then update oh. Closes [#46](https://github.com/shermanhuman/oh/issues/46): Codex logs every stop once its hooks are trusted, and the sugarhouse plugin tells Codex agents not to start the built-in `/goal`.

- oh-phoenix 1.0.2: the `daisyui` guide points a project without a brand package at brandkit's `brand` and `design` skills instead of the dropped `mapleset-design`, and its "⚠️ CRITICAL GOTCHAS" heading becomes "Drawer gotchas", numbered 1 to 4.
- oh 2.11.3: the release routine in a GitOps repository is its own path: in breakdown-infra, `scripts/stage.sh` then `scripts/promote.sh`, as PRs the user merges, with migrations running in the sync or the app's containers. `oh:release` gains the steps: list the pending migrations before staging and again on the promotion PR, name a destructive one in the PR and its merge task (the user's merge is their yes), check staging, and read the result from Argo; a revert doesn't undo a migration. With read-only cluster access a release is a PR, never a way around that access. The Phoenix migration procedure is for apps deployed by hand.
- oh 2.11.2: answer where the user engages (compound-v's rule): replies stay in the tab only when the user is talking there; everything else goes to the board, including a goal's intent questions when it started from the board. keep-going's question nudge also covers the intent phase, and says it's the hook, not the user.
- oh 2.11.1: mid-work questions go to the board, never the chat, except the four conversations that stay in the tab. Only a question that's cheap to undo goes ahead on a default; the rest are posted as `critical` and wait, with the work they don't touch carrying on. A step that's the user's (a merge, a push) is a board task with only its link in the chat. keep-going nudges once when the goal's owner ends a turn on a question in the plan or build phase, outside plan mode.
- oh-phoenix 1.0.1: the `daisyui` guide drops `shadow` from its dropdown snippet, takes themes from the project's brand package (brandkit) where it has one, and explains `row-hover`.
- oh 2.11.0: Sugarhouse is the board, the plan store and the decision store: *Questions* posts items with `sugar`, tasks for the user are task items, a goal's PRs go on its `goal.prs` label for the merge poller, its type on `goal.type`, and the `sugarhouse` MCP server ships in the plugin. The generic PR procedure, release prep, tasks for the user, the rough-edge kinds and the merge, rebase and refusal rules moved to compound-v (2.11.0); `pull-requests`, `release` and `rough-edges` keep this machine's specifics. While Sugarhouse is down, answers are kept on a local page and written to the board later, and a plan's approval waits for the board.
- oh 2.10.2: follow-up rounds and plan re-reviews after revisions run on Opus high; whole-diff rounds and a plan's first review stay on Fable high (a revision that changes scope or approach counts as a first review). Cuts Fable use, most of which went to repeat rounds.
- oh 2.10.1: a step waiting on the user doesn't stop the goal; the agent keeps working on what can move and sets `blocked` only when nothing can.
- oh 2.10.0: goals. An intent conversation one question at a time; goal and phase labels on the Herdr tab; a keep-going Stop hook that nudges once per turn in the build phase (Claude Code and Codex; off with `~/.local/state/oh/keep-going.off`); questions that come up mid-work default and continue unless they can't be undone; scope, taste, outward messages and new spending are never defaulted; tasks for the user come after pushing back, in a template with exact links and commands; a spend command. New skill `oh:goals`.
- oh 2.9.2: the release routine (rollout restarts, Argo refreshes, migration Jobs, deploy scripts) goes ahead without asking, but a destructive change inside it (a migration that drops a column or table, or deletes data) still waits for the user's yes, and the release skill checks the pending migrations before the Job runs. Deleting cloud resources (buckets, DNS records, VMs, managed databases) in an account that isn't local now waits for the user's yes too, by rule; the hook doesn't check it. Restored from before 2.9.0: the production list's scope (a cluster that isn't local), the rebase rule's reason, and listing a secret file's key names. That listing is now `grep -oE '^[A-Z_][A-Z0-9_]*=' FILE`: the secrets guard no longer passes `cut -d= -f1` or `grep -o '^[^=]*'`, which print a multi-line key's body.
- oh 2.9.1: waxseal asks for `gcloud auth application-default login` when its credentials expire (the guard named a plain login); a plan packet comes only when the work needs the user's approval or has open decisions; the no-browser and no-artifact rules cover the HTML-file fallback too.
- oh 2.9.0: the always-on rules are cut from about 9,350 to about 3,700 characters: short invariants stay, and each procedure lives in the skill that already held it, with a pointer sentence. A new `rough-edges` skill holds the rough-edge log's kinds and format. The attribution rule is gone (settings enforce it; Codex adds none). Questions bookend the user's attention (one packet after planning, one after reviews), and packets are linked by machine name so they open over the tailnet, with numbers shown as charts and explained tables.
- oh 2.8.0: oh has its own (private) marketplace, `mapleset`. A new process and secrets guard refuses killing by name or pattern (one specific process per `kill`) and printing credentials or private keys. Rules for cleaning up after a merge, flaky checks, not loosening permissions, no silent failures, no AI attribution lines and direct links; the second voice covers the instructions review tier and gets live web search (its command moved into `pull-requests`); `build-hooks.py` fails past a 9,500-character session-start budget; waxseal hand-off rules.
- oh 2.7.1: decision packets use a local page served on 127.0.0.1, not claude.ai artifacts.
- oh 2.7.0: *Questions* come as one decision packet on a web page (with `compound-v:interrogate` 2.6.0): research first, everything at once, show don't tell, More discussion on every decision, walkthroughs too. New *Rough edges* rule logs improvement signals on factory#8.
- oh 2.6.0: a PR leaves draft only when the user could merge it right now (based on the default branch, mergeable, up to date, green, review clean, bump landed); stacked PRs stay drafts until retargeted, and a ready PR that stops qualifying (the base moved, or a check went red) goes back to draft. Added to *Watch your pull requests* and the `pull-requests` skill.
- oh 2.5.0: the *Version bumps* rule and the `release` skill cover Rust: `Cargo.toml`, workspace version inheritance, refreshing `Cargo.lock`, and `--locked` validation.
- oh 2.4.1: the `waxseal` skill covers waxseal 0.6: `--from-key` copies a value waxseal already stores (another namespace, a new key name) instead of a stop-and-ask, plus the fixed-shape keyring recipe. The always-on rule lists `--from-key` as a value source.
- oh 2.4.0: always-on *Production guard* rule and a PreToolUse guard (`hooks/prod-guard.py`) that refuses merging PRs, pushing to a default branch, force-pushing and deleting repositories, and asks before `kubectl delete`/`drain`/`cordon`/scale-to-zero on non-local contexts, `helm uninstall`, and destructive SQL on remote databases (deny in Codex). Both guards share `hooks/shell.py`.
- oh 2.3.1: `pull-requests` follows the review loop's tiers and opens PRs as drafts before the first round; README rewritten around how I work, with gotchas.
- oh 2.3.0: always-on *Sealed secrets go through waxseal* rule, plus a narrow PreToolUse guard (`hooks/waxseal-guard.py`) that refuses `kubeseal`, `gcloud secrets` changes and value reads, and Secret Manager URLs given to curl/wget, except inside waxseal's and oh's own source trees.
- oh 2.2.0: always-on *Watch your pull requests* rule, with the commands in `pull-requests`: keep your open PRs mergeable and green, re-bump when the base moves, check before calling anything ready.
- oh 2.1.0: always-on *Questions* rule — the context for a multiple-choice question goes inside the question, one decision per question when the topic is unfamiliar, plain text when the user asks to clarify.
- 2.0.0: Promptherder herd → six Claude Code and Codex plugins. Always-on rules move into the `oh` plugin's session-start hook; the review procedure moves to `compound-v:review-loop`, with `oh` naming the reviewers (Fable high, Astra high via `codex exec`); stack and API skills become per-repository plugins; the `promptherder` skill is gone.
