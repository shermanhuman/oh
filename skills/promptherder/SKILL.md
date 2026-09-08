---
name: promptherder
description: Configure, inspect, and troubleshoot Promptherder 1.x native rule and skill distribution.
---

# Promptherder 1.x

Select targets explicitly: `promptherder install codex claude`, or interactive `install` with nothing preselected. `install none` saves no targets. Use `target list`, `target add`, and `target remove`; run bare `promptherder` to apply the selection. No host is a default.

`pull <alias-or-url>` downloads a herd without syncing. Sources remain in `.promptherder/herds/`; local additions live in `.promptherder/agent/`. Differing local overrides require source paths in settings `overrides`. `.promptherder/hard-rules.md` joins the baseline on sync. Edit sources, never generated host files.

Use `plan --json` to inspect content, origins, ownership, deletions, and diagnostics; `check` to validate; `doctor` for additional personal discovery checks; `explain <id>` for source tracing. The documented profile is not proof of runtime adherence.

Codex receives `AGENTS.md` and `.agents/skills/`; Claude receives a `CLAUDE.md` import bridge, `.claude/rules/`, and `.claude/skills/`. Other repository targets are Copilot, Cursor, Windsurf, Cline, and Antigravity. Gemini CLI is removed. Native workflow IDs are `workflow-<name>` (plus any configured prefix): `$workflow-plan` in Codex, `/workflow-plan` in Claude. Skill directories preserve resources and executable scripts; `herd.json.skills` can declare helper dependencies and host overlays.

Review legacy migration with `plan --adopt --json` before syncing with `--adopt`. User edits to tracked output are conflicts, not overwrite permission. After an interrupted apply, `recover` checks for subsequent edits before rollback.

Lockfiles record immutable revisions and content digests. Review changed herds with `plan --update-lock`, then apply `--update-lock`; `pull --locked` reproduces a recorded revision. Direct target sync rebuilds the installed consumer union without changing saved preferences.

`--scope user` explicitly selects personal installation for Codex/Claude in default layouts, with sources and settings under `~/.promptherder/`. Repository scope remains the default. Use the same scope for setup, pull, sync, and recovery. Read the installed version's help before relying on these commands; `@latest` can lag an unreleased feature branch.
