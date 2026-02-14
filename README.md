# Oh

A [promptherder](https://github.com/shermanhuman/promptherder) herd for cross-project environment rules and skills.

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

## What's Included

Environment-level rules and skills that apply across all your projects — things that are bigger than any single repo but smaller than a full methodology.

### Skills

| Skill     | Description                                          |
| --------- | ---------------------------------------------------- |
| `waxseal` | SealedSecrets management with GSM as source of truth |

### Rules

_None yet — add project-environment rules as needed._

## Structure

```
oh/
├── herd.json           # Herd metadata
├── skills/
│   └── waxseal/
│       └── SKILL.md    # WaxSeal SealedSecrets management
└── rules/              # (future: cross-project rules)
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
