# Oh

A [promptherder](https://github.com/shermanhuman/promptherder) herd — my personal collection of skills covering the tools, APIs, and patterns I use across projects.

> [!NOTE]
> This is not a general-purpose library. The skills here are specific to my stack (Phoenix, Telnyx, Tekmetric, etc.) and probably aren't useful to you directly. What _is_ useful is seeing how a herd is structured — if you want to build your own collection of reusable AI agent skills, this is a working example of how to do it with promptherder.

Named after [Sadaharu Oh](https://en.wikipedia.org/wiki/Sadaharu_Oh) — the greatest home run hitter in professional baseball history. 868 career home runs across 22 seasons with the Yomiuri Giants. If compound-v gives your AI agent superpowers, oh is the discipline and consistency that turns raw power into a record-breaking career. 王貞治.

## Install

```bash
# Install promptherder
go install github.com/shermanhuman/promptherder/cmd/promptherder@latest

# Select targets explicitly (Promptherder 1.x)
promptherder install codex claude

# Pull this herd
promptherder pull https://github.com/shermanhuman/oh

# Sync to agent targets
promptherder
```

Promptherder 1.x compiles native host rules and skill bundles. Codex uses `.agents/skills/`; Claude uses `.claude/skills/`. No host is enabled by default. Use the 1.0.0 feature build until it is published; existing locks need review with `plan --update-lock` before applying the update.

## What's Included

Skills covering the tools, APIs, and infrastructure patterns used across my projects.

### Skills

| Skill                 | Description                                                              |
| --------------------- | ------------------------------------------------------------------------ |
| `daisyui`             | DaisyUI v5 component library — semantic classes, themes, drawer gotchas  |
| `dockerfile`          | Docker best practices — Alpine pinning, security patches, multi-stage builds |
| `groq-api`            | Groq API syntax — Whisper transcription, audio processing                |
| `mise`                | Mise dev tool manager — installing, running, and configuring tools       |
| `phoenix`             | Core Phoenix patterns — context boundaries, LiveView, Ecto, architecture |
| `postmark-api`        | Postmark API syntax — transactional emails, batch, attachments           |
| `promptherder`        | CLI reference for syncing agent rules, skills, and workflows             |
| `release`             | Version preparation separated from explicitly requested publishing       |
| `tekmetric-api`       | Tekmetric REST API — auth, pagination, sync patterns, undocumented behaviors |
| `telnyx-call-control` | Telnyx Voice API v2 — call handling, recording, webhook events           |
| `waxseal`             | SealedSecrets management with GSM as source of truth                     |

### Rules

| Rule | Description |
|------|-------------|
| `mise` | Mise-first policy — mise first for tools; GitHub always through `mise exec -- gh` |
| `pull-requests` | PRs are releases: work in a worktree, test and review until clean locally, one PR per repository, reviews recorded on the PR; humans merge |
| `version-bump` | Bump version before opening PRs — use the `release` skill |

## Structure

```
oh/
├── herd.json
├── skills/
│   ├── daisyui/
│   │   └── SKILL.md
│   ├── dockerfile/
│   │   └── SKILL.md
│   ├── groq-api/
│   │   └── SKILL.md
│   ├── mise/
│   │   └── SKILL.md
│   ├── phoenix/
│   │   └── SKILL.md
│   ├── postmark-api/
│   │   └── SKILL.md
│   ├── promptherder/
│   │   └── SKILL.md
│   ├── release/
│   │   └── SKILL.md
│   ├── tekmetric-api/
│   │   └── SKILL.md
│   ├── telnyx-call-control/
│   │   └── SKILL.md
│   └── waxseal/
│       └── SKILL.md
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

## 1.0.0 alignment

Version preparation no longer implies publishing. PR rules reference one version policy, and mise-first tooling and mandatory pre-PR version bumps remain repository policy. Larger API/component guides now load from `references/`; the Tekmetric endpoint catalog is preserved. Static examples were corrected for HTTP failures, webhook envelopes, cache invalidation, and tuple-return handling. Dated sandbox observations are not current live-test claims.

These are opinionated repository instructions: prefer mise before competing tool managers, use `mise exec -- gh` for GitHub, bump the version before a PR, and leave merging to humans. Native-host portability changes the integration mechanism, not those preferences.
