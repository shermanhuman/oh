# Oh

My personal Claude Code and Codex plugins: the working agreements I want in every session, plus the stack and API knowledge for the projects I work on.

> [!NOTE]
> This is not a general-purpose library. The plugins are specific to my stack (Phoenix, Telnyx, Tekmetric, …) and my way of shipping. What _is_ useful is the shape: a personal plugin that fills in the choices a generic methodology like [Compound V](https://github.com/shermanhuman/compound-v) leaves open, and per-project plugins that only switch on where they apply.

Named after [Sadaharu Oh](https://en.wikipedia.org/wiki/Sadaharu_Oh) — the greatest home run hitter in professional baseball history. 868 career home runs across 22 seasons with the Yomiuri Giants. If Compound V gives your agent superpowers, Oh is the discipline and consistency that turns raw power into a record-breaking career. 王貞治.

## Plugins

| Plugin | What it holds | Where it's on |
|---|---|---|
| `oh` | Always-on: mise first, pull requests are releases, version bump per PR, reviewer choices (Fable high reviewers; Astra high through `codex exec` as the second voice). Skills: `pull-requests`, `release`, `mise`, `waxseal`, `dockerfile` | everywhere |
| `oh-phoenix` | `phoenix` (LiveView, Ecto, migrations, architecture and testing references), `daisyui` | Elixir repositories |
| `oh-tekmetric` | `tekmetric-api` with the full endpoint catalog | repositories that sync Tekmetric |
| `oh-telnyx` | `telnyx-call-control` | voice/SMS repositories |
| `oh-postmark` | `postmark-api` | repositories that send email |
| `oh-groq` | `groq-api` (Whisper transcription) | repositories that transcribe |

## Install

The plugins are listed in the Compound V marketplace (this repository has none of its own, so nothing gets installed twice).

```text
# Claude Code
/plugin marketplace add shermanhuman/compound-v
/plugin install oh@compound-v
/plugin install oh-phoenix@compound-v      # and the other oh-* plugins

# Codex
codex plugin marketplace add shermanhuman/compound-v
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

Codex reads a project's `.codex/config.toml` only once the project is trusted; trust the main checkout once and its worktrees follow.

### Codex notes

- **Hooks.** The `oh` and `compound-v` always-on rules arrive through session-start hooks. Codex skips plugin hooks, silently, until you trust them: open `/hooks` once and trust both. `codex exec` runs (Astra reviews) skip hooks; their briefs carry what they need.
- **Questions.** Codex's multiple-choice question tool is only available in Plan mode by default. To allow it in Default mode, enable the `default_mode_request_user_input` feature (`codex features`).

## Updating

Installed copies change when a plugin's version does: every PR here bumps each plugin it changes. In Claude Code, turn on auto-update for the marketplace in `/plugin`, or run `claude plugin update oh@compound-v`; in Codex, run `codex plugin marketplace upgrade compound-v`.

## License

MIT License — Copyright (c) 2026 Sherman Boyd

## Changelog

- 2.0.0: Promptherder herd → six Claude Code and Codex plugins. Always-on rules move into the `oh` plugin's session-start hook; the review procedure moves to `compound-v:review-loop`, with `oh` naming the reviewers (Fable high, Astra high via `codex exec`); stack and API skills become per-repository plugins; the `promptherder` skill is gone.
- 1.3.0: the always-on PR rule keeps only the policy; the procedure moved to the `pull-requests` skill. Review rounds loop only on must-fix findings.
- 1.2.0: PRs are releases (worktree, local tests and e2e, review until clean, reviews on the PR); digest-pinned migrations in the release skill.
- 1.0.0: version preparation separated from publishing; larger guides moved to `references/`.
