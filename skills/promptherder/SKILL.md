---
name: promptherder
description: Reference for the promptherder CLI — managing AI agent rules, skills, and workflows across multiple coding agents (Antigravity, Copilot). Use when installing herds, syncing targets, creating herd repos, or troubleshooting prompt distribution.
---

# Promptherder — CLI Reference

> Go CLI that fans out AI coding agent rules, skills, and workflows from one source to every agent you use.

**Source:** [github.com/shermanhuman/promptherder](https://github.com/shermanhuman/promptherder)

---

## Mental Model

Promptherder solves one problem: you write rules/skills/workflows once, and they get installed into every AI agent's expected directory structure.

```
herds (GitHub repos)          targets (agent directories)
┌──────────────┐
│ compound-v   │──┐
└──────────────┘  │    ┌──────────────────────┐
                  ├──→ │ .agent/              │  (Antigravity)
┌──────────────┐  │    │   rules/             │
│ oh           │──┤    │   skills/            │
└──────────────┘  │    │   workflows/         │
                  │    └──────────────────────┘
                  │    ┌──────────────────────┐
                  ├──→ │ .github/             │  (Copilot)
                  │    │   instructions/      │
                  │    │   prompts/           │
                  │    │   copilot-instructions.md │
                  │    └──────────────────────┘
```

### Key concepts

| Concept       | Description                                                                                |
| ------------- | ------------------------------------------------------------------------------------------ |
| **Herd**      | A Git repo containing rules, skills, and/or workflows. Has a `herd.json`.                  |
| **Target**    | An agent-specific output directory (`antigravity` → `.agent/`, `copilot` → `.github/`)     |
| **Merge**     | Multiple herds are combined into `.promptherder/agent/` (the staging area)                 |
| **Sync**      | Files from staging are installed to each target's directory                                |
| **Manifest**  | `.promptherder/manifest.json` — tracks what promptherder owns for clean updates            |
| **Variant**   | Agent-specific skill override (e.g., `ANTIGRAVITY.md` replaces `SKILL.md` for that target) |
| **Generated** | Files the agent creates (e.g., `stack.md`) — promptherder never overwrites these           |

---

## Install

```bash
go install github.com/shermanhuman/promptherder/cmd/promptherder@latest
```

---

## CLI Commands

### `promptherder` (bare)

Merges all installed herds, then syncs to all targets.

```bash
promptherder                    # Sync everything
promptherder -dry-run           # Preview without writing
promptherder -v                 # Verbose structured logging
```

**What happens:**

1. Discover herds in `.promptherder/herds/`
2. Clean previous herd files from `.promptherder/agent/`
3. Merge all herds into `.promptherder/agent/` (conflict = error)
4. Install to Antigravity target (`.agent/`)
5. Install to Copilot target (`.github/`)
6. Write manifest, clean stale files

### `promptherder <target>`

Sync a single target only.

```bash
promptherder copilot            # Sync Copilot only
promptherder antigravity        # Sync Antigravity only
promptherder copilot -dry-run   # Preview Copilot sync
```

### `promptherder pull <git-url>`

Download and install a herd from a GitHub repository.

```bash
promptherder pull https://github.com/shermanhuman/compound-v
promptherder pull https://github.com/shermanhuman/oh
promptherder pull https://github.com/user/my-herd -dry-run
```

**What happens:**

1. Derives herd name from URL (last path segment, sans `.git`)
2. Downloads tarball via GitHub API (no git binary needed)
3. Extracts to `.promptherder/herds/<name>/`
4. Validates `herd.json` exists
5. Does NOT auto-sync — run bare `promptherder` after pulling

### Flags

| Flag               | Description                                            |
| ------------------ | ------------------------------------------------------ |
| `-dry-run`         | Show what would happen without writing                 |
| `-include <globs>` | Comma-separated glob patterns to filter (Copilot only) |
| `-v`               | Verbose structured logging to stderr                   |
| `-version`         | Print version and exit                                 |

---

## Directory Structure

### In a herd repo (the source)

```
my-herd/
├── herd.json              # Required: {"name": "my-herd", "version": "0.1.0"}
├── rules/
│   └── my-rules.md        # Always-on rules (YAML frontmatter + Markdown)
├── skills/
│   └── my-skill/
│       ├── SKILL.md        # Generic skill instructions
│       ├── ANTIGRAVITY.md  # Optional: Antigravity-specific variant
│       └── COPILOT.md      # Optional: Copilot-specific variant
└── workflows/
    └── plan.md             # Slash command workflow
```

### In a project repo (the consumer)

```
my-project/
├── .promptherder/
│   ├── herds/                    # Downloaded herds (gitignored)
│   │   ├── compound-v/
│   │   └── oh/
│   ├── agent/                    # Merged staging area (gitignored)
│   │   ├── rules/
│   │   ├── skills/
│   │   └── workflows/
│   ├── convos/                   # Conversation artifacts (gitignored)
│   ├── manifest.json             # Tracks owned files
│   ├── settings.json             # Optional: command prefix config
│   ├── hard-rules.md             # Project rules (tracked in git)
│   └── future-tasks.md           # Deferred ideas (tracked in git)
├── .agent/                       # Antigravity target (gitignored)
│   ├── rules/
│   ├── skills/
│   └── workflows/
├── .github/                      # Copilot target
│   ├── instructions/
│   ├── prompts/
│   └── copilot-instructions.md
```

---

## File Formats

### `herd.json`

```json
{
  "name": "my-herd",
  "version": "0.1.0"
}
```

### `SKILL.md`

```markdown
---
name: my-skill
description: What this skill does and when to use it.
---

# Skill Title

Instructions in plain Markdown...
```

- `name` — lowercase, hyphens only
- `description` — used by the agent to decide relevance (max 1024 chars)

### Rule files

```markdown
---
trigger: always_on
---

# Rule Title

Rule content...
```

The `trigger: always_on` frontmatter means the rule is always active. The `applyTo` field can restrict to specific file patterns.

### Workflow files

```markdown
---
description: What this workflow does
---

Step-by-step instructions...
```

### `settings.json`

```json
{
  "command_prefix": "v-",
  "command_prefix_enabled": true
}
```

When enabled, workflow filenames get prefixed (e.g., `plan.md` → `v-plan.md`). Useful to namespace commands across herds.

### `manifest.json`

```json
{
  "version": 2,
  "generated_at": "2026-02-13T22:00:00Z",
  "targets": {
    "herds": [".promptherder/agent/rules/compound-v.md", "..."],
    "antigravity": [".agent/rules/compound-v.md", "..."],
    "copilot": [".github/instructions/compound-v.instructions.md", "..."]
  },
  "generated": ["stack.md"]
}
```

The `generated` list protects files the agent creates — promptherder will never overwrite them.

---

## Target Behavior

### Antigravity

Copies `.promptherder/agent/` → `.agent/` preserving directory structure.

- Skills: Uses `ANTIGRAVITY.md` variant if present, otherwise `SKILL.md`
- Skills: Skips `COPILOT.md` variant files
- Workflows: Applies command prefix from settings
- Hard rules: Copies `.promptherder/hard-rules.md` → `.agent/rules/hard-rules.md`
- Generated files: Never overwrites files listed in manifest's `generated` array

### Copilot

Transforms and writes to `.github/`:

- Rules → `.github/instructions/*.instructions.md` (with Copilot frontmatter)
- Always-on rules → concatenated into `.github/copilot-instructions.md`
- Skills → `.github/prompts/*.prompt.md` (converted from SKILL.md format)
- Skills: Uses `COPILOT.md` variant if present, otherwise `SKILL.md`
- Workflows → `.github/prompts/*.prompt.md` (with Copilot frontmatter, turbo annotations stripped)

---

## Skill Variants

A skill directory can contain agent-specific variants:

```
skills/my-skill/
├── SKILL.md           # Generic (used if no variant matches)
├── ANTIGRAVITY.md     # Used by Antigravity target (replaces SKILL.md)
└── COPILOT.md         # Used by Copilot target (replaces SKILL.md)
```

When a variant exists for a target, it is installed **as** `SKILL.md` (or converted to `.prompt.md` for Copilot). The generic version is skipped.

---

## Conflict Detection

If two herds provide the same file path, promptherder errors:

```
conflict: rules/browser.md provided by both herd "compound-v" and "oh"
```

**Resolution:** Remove the duplicate from one herd, or rename the file.

---

## Typical Workflow

```bash
# Initial setup
promptherder pull https://github.com/shermanhuman/compound-v
promptherder pull https://github.com/shermanhuman/oh
promptherder

# After updating a herd
promptherder pull https://github.com/shermanhuman/oh   # Re-downloads
promptherder                                            # Re-syncs

# Preview changes
promptherder -dry-run

# Sync single target
promptherder copilot
```

---

## Recommended `.gitignore`

```
# Promptherder generated artifacts
.promptherder/
.agent/
.agents/
.antigravity/
.github/prompts/
.github/instructions/
.github/copilot-instructions.md
```

Keep `hard-rules.md` and `future-tasks.md` tracked if you want them version-controlled — but note they live under `.promptherder/` which is gitignored by default.

---

## Creating a New Herd

1. Create a GitHub repo with this structure:

```
my-herd/
├── herd.json          # {"name": "my-herd", "version": "0.1.0"}
├── .gitignore         # Ignore .promptherder/, .agent/, .github/ generated dirs
├── LICENSE
├── README.md
├── skills/
│   └── my-skill/
│       └── SKILL.md
└── rules/
    └── my-rule.md
```

2. Only `rules/`, `skills/`, and `workflows/` directories are merged. Everything else (README, LICENSE, herd.json) is metadata.

3. Push to GitHub, then pull from any project:

```bash
promptherder pull https://github.com/user/my-herd
promptherder
```

---

## Gotchas

- `promptherder pull` does NOT auto-sync — always run bare `promptherder` after pulling
- Herd merge order is **alphabetical by name** — deterministic but affects conflict errors
- Only `rules/`, `skills/`, and `workflows/` directories are copied from herds
- The `generated` list in manifest protects user-created files — add filenames there if the agent creates files you want to keep
- Copilot target strips `// turbo` and `// turbo-all` annotations (Antigravity-specific)
- No git binary required — pull uses GitHub API tarball download
- Command prefix only applies to workflow files, not skills or rules
