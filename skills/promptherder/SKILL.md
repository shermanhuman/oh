---
name: promptherder
description: Reference for the promptherder CLI — syncs AI agent rules, skills, and workflows from herd repos to agent targets. Use when installing, updating, or troubleshooting prompt distribution.
---

# Promptherder

Go CLI that manages AI agent configuration per repo. `.promptherder/` is the **source of truth** for each repository's agent rules, skills, and workflows.

## How It Works

```
Sources                          Agent targets (local)
┌──────────────┐
│ herds (GitHub)│──┐
└──────────────┘  │
                  ├──→  .agent/         (Antigravity)
┌──────────────┐  ├──→  .github/        (Copilot)
│ repo-local   │──┘
│ (.promptherder/agent/)
└──────────────┘
```

- **Herds** provide shared skills/rules across repos (pulled from GitHub)
- **Repo-local** files in `.promptherder/agent/` add per-project skills, rules, or overrides
- **`hard-rules.md`** in `.promptherder/` contains always-on rules specific to this repo
- `promptherder` merges everything and fans out to each agent target
- `.promptherder/manifest.json` tracks what files promptherder owns

## Commands

```bash
# Install a herd
promptherder pull https://github.com/shermanhuman/compound-v
promptherder pull https://github.com/shermanhuman/oh

# Sync to all targets (run after every pull)
promptherder

# Preview without writing
promptherder -dry-run

# Sync one target only
promptherder copilot
promptherder antigravity
```

## Herd Structure

A herd is a GitHub repo with `herd.json` and content in `rules/`, `skills/`, `workflows/`:

```
my-herd/
├── herd.json        # {"name": "my-herd", "version": "0.1.0"}
├── rules/
│   └── my-rule.md
├── skills/
│   └── my-skill/
│       └── SKILL.md
└── workflows/
    └── plan.md
```

Only `rules/`, `skills/`, and `workflows/` are synced. Everything else is metadata.

## Key Facts

- `pull` downloads but does **not** sync — always run bare `promptherder` after
- Two herds providing the same file path = conflict error
- Files listed in manifest's `generated` array (e.g., `stack.md`) are never overwritten
- Skills can have target-specific variants: `COPILOT.md` or `ANTIGRAVITY.md` override `SKILL.md`
- No git binary required — pull uses GitHub API tarball
