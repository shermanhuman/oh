# Oh

A [promptherder](https://github.com/shermanhuman/promptherder) herd — my personal collection of skills covering the tools, APIs, and patterns I use across projects.

**This is not a general-purpose library.** The skills here are specific to my stack (Phoenix, Telnyx, Tekmetric, etc.) and probably aren't useful to you directly. What _is_ useful is seeing how a herd is structured — if you want to build your own collection of reusable AI agent skills, this is a working example of how to do it with promptherder.

Named after [Sadaharu Oh](https://en.wikipedia.org/wiki/Sadaharu_Oh) — the greatest home run hitter in professional baseball history. 868 career home runs across 22 seasons with the Yomiuri Giants. If compound-v gives your AI agent superpowers, oh is the discipline and consistency that turns raw power into a record-breaking career. 王貞治.

## Install

```bash
# Install promptherder
go install github.com/shermanhuman/promptherder/cmd/promptherder@latest

# Pull this herd
promptherder pull https://github.com/shermanhuman/oh

# Sync to agent targets
promptherder
```

Files install to `.agents/` (Antigravity default since v1.14). Legacy `.agent/` is still read by Antigravity for backward compat — promptherder will prompt you to migrate when you next run it.

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
| `release`             | Semver release workflow — bump, tag, push, verify CI (Go + Elixir)       |
| `tekmetric-api`       | Tekmetric REST API — auth, pagination, sync patterns, undocumented behaviors |
| `telnyx-call-control` | Telnyx Voice API v2 — call handling, recording, webhook events           |
| `waxseal`             | SealedSecrets management with GSM as source of truth                     |

### Rules

| Rule | Description |
|------|-------------|
| `mise` | Mise-first policy — always prefer mise for tool installation and execution |
| `no-merge` | Merging is a human task — agents create PRs, humans merge them |

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
    └── no-merge.md
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
