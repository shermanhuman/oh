# Oh

My personal Claude Code and Codex plugins: the working agreements I want in every session, plus the stack and API knowledge for the projects I work on.

> [!NOTE]
> This is not a general-purpose library. The plugins are specific to my stack (Phoenix, Telnyx, Tekmetric, …) and my way of shipping. What _is_ useful is the shape: a personal plugin that fills in the choices a generic methodology like [Compound V](https://github.com/shermanhuman/compound-v) leaves open, and per-project plugins that only switch on where they apply.

Named after [Sadaharu Oh](https://en.wikipedia.org/wiki/Sadaharu_Oh) — the greatest home run hitter in professional baseball history. 868 career home runs across 22 seasons with the Yomiuri Giants. If Compound V gives your agent superpowers, Oh is the discipline and consistency that turns raw power into a record-breaking career. 王貞治.

## Plugins

| Plugin | What it holds | Where it's on |
|---|---|---|
| `oh` | The always-on working agreements below, and the skills `pull-requests` (the release procedure behind them), `release`, `mise`, `waxseal` and `dockerfile` | everywhere |
| `oh-phoenix` | `phoenix` (LiveView, Ecto, migrations, architecture and testing references), `daisyui` | Elixir repositories |
| `oh-tekmetric` | `tekmetric-api` with the full endpoint catalog | repositories that sync Tekmetric |
| `oh-telnyx` | `telnyx-call-control` | voice/SMS repositories |
| `oh-postmark` | `postmark-api` | repositories that send email |
| `oh-groq` | `groq-api` (Whisper transcription) | repositories that transcribe |

## How I work on top of Compound V

Compound V's [workflow](https://github.com/shermanhuman/compound-v#the-workflow) is the frame: pick, plan, review the plan, interrogate, build in a worktree, run the review loop, merge, file follow-ups. Oh adds my choices and the reasons for them:

- **Mise first.** Every tool comes from mise, and runs through `mise exec` when the shell isn't activated, so nothing gets installed twice in different ways.
- **A pull request is a release.** I keep one open PR per repository, batch the work, and test it locally before it opens. I merge. In my plugin repositories, PRs stay drafts until the last review round is clean (their `AGENTS.md` says so).
- **Worktrees, always.** My main checkouts run dev servers and sometimes hold another session's branch.
- **Watch your own PRs.** After every push, the agent watches CI and mergeability, because I kept being the one who found the red check or the conflict.
- **A version bump in every PR, done last.** It's re-applied when the base moves, because two PRs that set the same version line merge cleanly and then fail CI.
- **Sealed secrets only through waxseal**, one visible command per call, with a guard hook that refuses `kubeseal`, `gcloud secrets` changes and value reads, and Secret Manager URLs (details in the `oh:waxseal` skill and the hook text).
- **Questions carry their own context**, because text above a question widget goes unread.
- **Reviewers:** Fable at high effort for review subagents, and Astra high through `codex exec` as the second voice.
- **`/next` without the prefix.** A one-line personal skill at `~/.claude/skills/next/SKILL.md` ("Use the `compound-v:next` skill with: $ARGUMENTS") lets me type `/next` instead of `/compound-v:next` in Claude Code. A plugin can't add a bare command, so it lives only on my machine; in Codex it's still `$compound-v:next`.

## Install

The plugins are listed in the Compound V marketplace (this repository has none of its own, so nothing gets installed twice). `oh` builds on Compound V, so install that too.

Claude Code:

```bash
claude plugin marketplace add shermanhuman/compound-v
claude plugin install compound-v@compound-v
claude plugin install oh@compound-v
claude plugin install oh-phoenix@compound-v
```

Codex:

```bash
codex plugin marketplace add shermanhuman/compound-v
codex plugin add compound-v@compound-v
codex plugin add oh@compound-v
codex plugin add oh-phoenix@compound-v
```

Install the other `oh-*` plugins the same way. Start a new Claude Code session (or run `/reload-plugins`). In Codex, open `/hooks` and trust oh's two hooks (the session-start rules and the waxseal guard) and Compound V's. Updating works as in [Compound V's README](https://github.com/shermanhuman/compound-v#updating): in Claude Code, auto-update or `claude plugin update oh@compound-v`; in Codex, `codex plugin add oh@compound-v`.

## Stack and API plugins per repository

The `oh-*` plugins are installed once at user scope, switched off in user settings and switched on in each repository that needs them, as [Compound V describes](https://github.com/shermanhuman/compound-v#switching-a-plugin-on-per-repository). Codex reads a repository's `.codex/config.toml` only once that project path is trusted: trust each main checkout once, and its worktrees follow.

## Gotchas

- **Astra can't post.** It runs `codex exec -s read-only`, so it can't post comments or call MCP tools. Post its report yourself, unchanged, under an "Astra high (Codex)" header.
- **`codex exec` skips hooks you haven't trusted**, and Astra runs don't use `--dangerously-bypass-hook-trust`, so review briefs carry the rules they need.
- **Codex's question tool works in Plan mode only by default.** To allow it in Default mode, run `codex features enable default_mode_request_user_input` (still marked under development in Codex 0.162.1).
- **The waxseal guard is a backstop, not a sandbox.** It checks only what a shell would execute, fails open on input it can't handle, and needs `python3`.
- **After `codex plugin add oh-<name>@compound-v`**, that plugin's `enabled = true` comes back in `~/.codex/config.toml`. Switch it off again for your user.
- **Cloud sessions load no plugins**, so each repository's `AGENTS.md` repeats the rules that must always hold: I merge, a PR is a release, every PR bumps the version.
- **Any `mise exec` in a worktree with an untrusted `mise.toml` fails**, including `mise exec -- gh pr checks --watch`. Run `mise trust <worktree>/mise.toml` first, or run it from a directory without one.

## Upgrading from 1.x

1.x was a [Promptherder](https://github.com/shermanhuman/promptherder) herd. In each repository that pulled it, follow [Compound V's upgrade notes](https://github.com/shermanhuman/compound-v/blob/main/docs/upgrading-from-1x.md) with the `oh` herd in place of `compound-v`: remove `.promptherder/herds/oh` (and its `lock.json` entry) before the re-sync, and in the final check also look for the old copies of oh's skills (`mise`, `pull-requests`, `release`, `waxseal`, `dockerfile`, `phoenix`, `daisyui`, `tekmetric-api`, `telnyx-call-control`, `postmark-api`, `groq-api`, `promptherder`) under `.claude/skills/` and `.agents/skills/`. Then install the plugins as above and switch the stack and API plugins on per repository.

## License

MIT License — Copyright (c) 2026 Sherman Boyd

## Changelog

- oh 2.3.1: `pull-requests` follows the review loop's tiers (light for prose, full with the instructions pass for agent-instruction files); README rewritten around how I work, with gotchas.
- oh 2.3.0: always-on *Sealed secrets go through waxseal* rule, plus a narrow PreToolUse guard (`hooks/waxseal-guard.py`) that refuses `kubeseal`, `gcloud secrets` changes and value reads, and Secret Manager URLs given to curl/wget, except inside waxseal's and oh's own source trees.
- oh 2.2.0: always-on *Watch your pull requests* rule, with the commands in `pull-requests`: keep your open PRs mergeable and green, re-bump when the base moves, check before calling anything ready.
- oh 2.1.0: always-on *Questions* rule — the context for a multiple-choice question goes inside the question, one decision per question when the topic is unfamiliar, plain text when the user asks to clarify.
- 2.0.0: Promptherder herd → six Claude Code and Codex plugins. Always-on rules move into the `oh` plugin's session-start hook; the review procedure moves to `compound-v:review-loop`, with `oh` naming the reviewers (Fable high, Astra high via `codex exec`); stack and API skills become per-repository plugins; the `promptherder` skill is gone.
