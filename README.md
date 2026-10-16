# Oh

My personal Claude Code and Codex plugins: the working agreements I want in every session, plus the stack and API knowledge for the projects I work on.

> [!NOTE]
> This is not a general-purpose library. The plugins are specific to my stack (Phoenix, Telnyx, Tekmetric, …) and my way of shipping. What _is_ useful is the shape: a personal plugin that fills in the choices a generic methodology like [Compound V](https://github.com/shermanhuman/compound-v) leaves open, and per-project plugins that only switch on where they apply.

Named after [Sadaharu Oh](https://en.wikipedia.org/wiki/Sadaharu_Oh) — the greatest home run hitter in professional baseball history. 868 career home runs across 22 seasons with the Yomiuri Giants. If Compound V gives your agent superpowers, Oh is the discipline and consistency that turns raw power into a record-breaking career. 王貞治.

## Plugins

| Plugin | What it holds | Where it's on |
|---|---|---|
| `oh` | Always-on: mise first, pull requests are releases, version bump per PR, questions with their context inside, watching your own PRs, reviewer choices (Fable high reviewers; Astra high through `codex exec` as the second voice). Skills: `pull-requests`, `release`, `mise`, `waxseal`, `dockerfile` | everywhere |
| `oh-phoenix` | `phoenix` (LiveView, Ecto, migrations, architecture and testing references), `daisyui` | Elixir repositories |
| `oh-tekmetric` | `tekmetric-api` with the full endpoint catalog | repositories that sync Tekmetric |
| `oh-telnyx` | `telnyx-call-control` | voice/SMS repositories |
| `oh-postmark` | `postmark-api` | repositories that send email |
| `oh-groq` | `groq-api` (Whisper transcription) | repositories that transcribe |

## Install

The plugins are listed in the Compound V marketplace (this repository has none of its own, so nothing gets installed twice).

`oh` builds on Compound V (its review loop and plan format), so install that too.

```text
# Claude Code
/plugin marketplace add shermanhuman/compound-v
/plugin install compound-v@compound-v
/plugin install oh@compound-v
/plugin install oh-phoenix@compound-v      # and the other oh-* plugins

# Codex
codex plugin marketplace add shermanhuman/compound-v
codex plugin add compound-v@compound-v
codex plugin add oh@compound-v
codex plugin add oh-phoenix@compound-v     # and the other oh-* plugins
```

### Stack and API plugins per repository

Install them all once, switch them off for your user, and switch them on in each repository that needs them.

**Claude Code** — in `~/.claude/settings.json`:

```json
{ "enabledPlugins": { "oh-phoenix@compound-v": false, "oh-tekmetric@compound-v": false } }
```

and in the repository's committed `.claude/settings.json`:

```json
{ "enabledPlugins": { "oh-phoenix@compound-v": true, "oh-tekmetric@compound-v": true } }
```

Project settings override user settings, and git worktrees of the repository pick them up too.

**Codex** — set `enabled = false` under `[plugins."oh-phoenix@compound-v"]` in `~/.codex/config.toml`, and commit a `.codex/config.toml` in the repository:

```toml
[plugins."oh-phoenix@compound-v"]
enabled = true
```

Codex reads a project's `.codex/config.toml` only once that project is trusted: trust each repository's main checkout once (a trusted parent folder doesn't count) and its worktrees follow.

### Codex notes

- **Hooks.** The `oh` and `compound-v` always-on rules arrive through session-start hooks. Codex skips plugin hooks, silently, until you trust them: open `/hooks` once and trust both. A `codex exec` run skips hooks you haven't trusted; Astra review briefs carry what they need either way.
- **Questions.** Codex's multiple-choice question tool is only available in Plan mode by default. To allow it in Default mode, enable the `default_mode_request_user_input` feature (`codex features`).

## Upgrading from 1.x

1.x was a [Promptherder](https://github.com/shermanhuman/promptherder) herd. In each repository that pulled it: remove `oh` from `.promptherder/` (the herd and its `lock.json` entry), delete the generated output it produced (`AGENTS.md`/`CLAUDE.md` sections, `.claude/skills/`, `.agents/skills/` copies of `mise`, `pull-requests`, `release`, `phoenix` and the rest) while keeping any hand-written instructions, then install the plugins as above and switch the stack and API plugins on per repository.

## Updating

Installed copies change when a plugin's version does: every PR here bumps each plugin it changes. In Claude Code, turn on auto-update for the marketplace in `/plugin`, or run `claude plugin update oh@compound-v`; in Codex, run `codex plugin marketplace upgrade compound-v`.

## License

MIT License — Copyright (c) 2026 Sherman Boyd

## Changelog

- oh 2.2.0: always-on *Watch your pull requests* rule, with the commands in `pull-requests`: keep your open PRs mergeable and green, re-bump when the base moves, check before calling anything ready.
- oh 2.1.0: always-on *Questions* rule — the context for a multiple-choice question goes inside the question, one decision per question when the topic is unfamiliar, plain text when the user asks to clarify.
- 2.0.0: Promptherder herd → six Claude Code and Codex plugins. Always-on rules move into the `oh` plugin's session-start hook; the review procedure moves to `compound-v:review-loop`, with `oh` naming the reviewers (Fable high, Astra high via `codex exec`); stack and API skills become per-repository plugins; the `promptherder` skill is gone.
- 1.3.0: the always-on PR rule keeps only the policy; the procedure moved to the `pull-requests` skill. Review rounds loop only on must-fix findings.
- 1.2.0: PRs are releases (worktree, local tests and e2e, review until clean, reviews on the PR); digest-pinned migrations in the release skill.
- 1.0.0: version preparation separated from publishing; larger guides moved to `references/`.
