# Oh

A [promptherder](https://github.com/shermanhuman/promptherder) herd — my personal collection of skills covering the tools, APIs, and patterns I use across projects.

> [!NOTE]
> This is not a general-purpose library. The skills here are specific to my stack (Phoenix, Telnyx, Tekmetric, etc.) and probably aren't useful to you directly. What _is_ useful is seeing how a herd is structured — if you want to build your own collection of reusable AI agent skills, this is a working example of how to do it with promptherder.

Named after [Sadaharu Oh](https://en.wikipedia.org/wiki/Sadaharu_Oh) — the greatest home run hitter in professional baseball history. 868 career home runs across 22 seasons with the Yomiuri Giants. If compound-v gives your AI agent superpowers, oh is the discipline and consistency that turns raw power into a record-breaking career. 王貞治.

## Install

```bash
# Install promptherder (through mise)
mise use -g github:shermanhuman/promptherder

# Select targets explicitly (Promptherder 1.x)
promptherder install codex claude

# Pull this herd
promptherder pull https://github.com/shermanhuman/oh

# Sync to agent targets
promptherder
```

Promptherder 1.x compiles native host rules and skill bundles. Codex uses `.agents/skills/`; Claude uses `.claude/skills/`. No host is enabled by default. Review existing locks with `plan --update-lock` before applying an update.

## What's Included

Skills covering the tools, APIs, and infrastructure patterns used across my projects. API and component skills keep a short `SKILL.md` and load their detail from `references/` only when needed.

### Skills

| Skill                 | Description                                                              |
| --------------------- | ------------------------------------------------------------------------ |
| `daisyui`             | DaisyUI v5 component library — semantic classes, themes, drawer gotchas  |
| `dockerfile`          | Docker best practices — Alpine pinning, security patches, multi-stage builds |
| `groq-api`            | Groq API syntax — Whisper transcription, audio processing                |
| `mise`                | Mise dev tool manager — installing, running, and configuring tools       |
| `phoenix`             | Core Phoenix patterns — context boundaries, LiveView, Ecto, migrations, testing |
| `postmark-api`        | Postmark API syntax — transactional emails, batch, attachments           |
| `promptherder`        | CLI reference for syncing agent rules, skills, and workflows             |
| `pull-requests`       | PR procedure — worktree, local tests and e2e, review rounds, gh pr create, reviews on the PR |
| `release`             | Version preparation separated from explicitly requested publishing       |
| `tekmetric-api`       | Tekmetric REST API — auth, pagination, sync patterns, undocumented behaviors |
| `telnyx-call-control` | Telnyx Voice API v2 — call handling, recording, webhook events           |
| `waxseal`             | SealedSecrets management with GSM as source of truth                     |

### Rules

| Rule | Description |
|------|-------------|
| `mise` | Mise-first policy — mise first for tools; GitHub always through `mise exec -- gh` |
| `pull-requests` | PRs are releases: one PR per repository, worktree until the PR, local tests and e2e, fresh reviewers until no must-fix findings remain (polish fixed in one pass, stop after three rounds in a row with must-fix findings), reviews on the PR; the user merges. The procedure is in the `pull-requests` skill |
| `version-bump` | Every PR bumps the version, last — use the `release` skill |

Rules are always on (they land in every session's `AGENTS.md`), so they hold only the policy; procedures live in skills that load when needed.

## Structure

```
oh/
├── herd.json
├── skills/
│   ├── daisyui/
│   │   ├── SKILL.md
│   │   └── references/guide.md
│   ├── dockerfile/
│   │   └── SKILL.md
│   ├── groq-api/
│   │   ├── SKILL.md
│   │   └── references/guide.md
│   ├── mise/
│   │   └── SKILL.md
│   ├── phoenix/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── postmark-api/
│   │   ├── SKILL.md
│   │   └── references/guide.md
│   ├── promptherder/
│   │   └── SKILL.md
│   ├── pull-requests/
│   │   └── SKILL.md
│   ├── release/
│   │   ├── SKILL.md
│   │   └── references/phoenix-migrations.md
│   ├── tekmetric-api/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── telnyx-call-control/
│   │   ├── SKILL.md
│   │   └── references/guide.md
│   └── waxseal/
│       ├── SKILL.md
│       └── references/guide.md
└── rules/
    ├── mise.md
    ├── pull-requests.md
    └── version-bump.md
```

## How it fits with Compound V

`oh` is a companion herd to [compound-v](https://github.com/shermanhuman/compound-v). Compound V provides the methodology (planning, execution, review). Oh provides environment-specific knowledge — the tools, services, and patterns specific to your infrastructure that every repo needs to know about.

```
compound-v  →  methodology (how to work)
oh          →  environment (what you work with)
stack.md    →  project (what you're building)
```

Pull both into any repo:

```bash
promptherder pull https://github.com/shermanhuman/compound-v
promptherder pull https://github.com/shermanhuman/oh
promptherder
```

## License

MIT License — Copyright (c) 2026 Sherman Boyd

## Changelog

- 1.3.0: the always-on PR rule keeps only the policy; the procedure moved to the `pull-requests` skill. Release skill de-duplicated, with its migration runbook in a reference. Phoenix skill grown with LiveView, Ecto, migration and testing references. Reference guides gained a Contents list. Review rounds now loop only on must-fix findings; polish is fixed in one pass with a quick diff check, and three rounds in a row with must-fix findings stop the work for the user.
- 1.2.0: PRs are releases (worktree, local tests and e2e, review until clean, reviews on the PR); digest-pinned migrations in the release skill.
- 1.0.0: version preparation separated from publishing; larger guides moved to `references/`.

These are opinionated repository instructions: prefer mise before competing tool managers, use `mise exec -- gh` for GitHub, bump the version in every PR, and leave merging to the user. Native-host portability changes the integration mechanism, not those preferences.
