---
name: promptherder
description: Configures, inspects and troubleshoots Promptherder 1.x herds and their generated AGENTS.md, CLAUDE.md and skill folders. Use when running promptherder, editing a herd (herd.json, rules/, skills/), or when generated instruction files look wrong.
---

# Promptherder 1.x

Install and upgrade it through mise: `mise use -g github:shermanhuman/promptherder`.

Select targets explicitly: `promptherder install codex claude`, or interactive `install` with nothing preselected. `install none` saves no targets. Use `target list`, `target add`, and `target remove`; run bare `promptherder` to apply the selection. No host is a default.

`pull <alias-or-url>` downloads a herd without syncing. Sources remain in `.promptherder/herds/`; local additions live in `.promptherder/agent/`. Differing local overrides require source paths in settings `overrides`. `.promptherder/hard-rules.md` joins the baseline on sync. Edit sources, never generated host files.

Rule `activation` is `always` (concatenated into `AGENTS.md`, which Claude loads through the `CLAUDE.md` import; one always-on file each for Windsurf and Antigravity), `paths` (native scoped rules; Codex gets a "when working on X, read Y" line), `manual` (a manual skill `rule-<id>`) or `relevance` (an automatic skill `rule-<id>`). Legacy `trigger`, `applyTo` and `globs` are translated.

Keep skill frontmatter to `name` and `description` (plus `license`, `compatibility`, `metadata`, `disable-model-invocation`, `user-invocable`). Frontmatter is copied unchanged to every target, so any other key (`when_to_use`, `allowed-tools`, `paths`) warns once per target and fails `check --strict`. Put trigger phrases ("Use when …") in `description`, up to 1,024 characters. A `claude` overlay fails the plan when Cline or Copilot is selected, because they share or also scan `.claude/skills`.

Use `plan --json` to inspect content, origins, ownership, deletions, and diagnostics; `check` to validate; `doctor` for additional personal discovery checks; `explain <id>` for source tracing. The documented profile is not proof of runtime adherence.

Codex receives `AGENTS.md` and `.agents/skills/`; Claude receives a `CLAUDE.md` import bridge, `.claude/rules/`, and `.claude/skills/`. Other repository targets are Copilot, Cursor, Windsurf, Cline, and Antigravity. Gemini CLI is removed. Native workflow IDs are `workflow-<name>` (plus any configured prefix): `$workflow-plan` in Codex, `/workflow-plan` in Claude. Skill directories preserve resources and executable scripts; `herd.json.skills` can declare helper dependencies and host overlays.

Review legacy migration with `plan --adopt --json` before syncing with `--adopt`. User edits to tracked output are conflicts, not overwrite permission. After an interrupted apply, `recover` checks for subsequent edits before rollback.

Lockfiles record immutable revisions and content digests. Review changed herds with `plan --update-lock`, then apply `--update-lock`; `pull --locked` reproduces a recorded revision. Direct target sync rebuilds the installed consumer union without changing saved preferences.

`--scope user` explicitly selects personal installation for Codex/Claude in default layouts, with sources and settings under `~/.promptherder/`. Repository scope remains the default. Use the same scope for setup, pull, sync, and recovery. Read the installed version's help before relying on these commands; `@latest` can lag an unreleased feature branch.
