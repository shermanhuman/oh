---
trigger: always_on
---

# Pull Request Rules

## How to open a PR

Follow these steps in order:

1. **Bump the version** — If the repo contains `herd.json`, `mix.exs`, or `go.mod`, use the `release` skill to bump the version before creating the PR. Default to `patch` for minor changes. The CI version-check gate will reject PRs without a version bump.

2. **Open the PR with `gh`** — Always use `mise exec -- gh pr create`. Never use a browser agent for GitHub operations that `gh` can handle.

```bash
mise exec -- gh pr create \
  --title "type: short description" \
  --body "..." \
  --base <default-branch> \
  --head <branch>
```

## Merging is a human task

**Never merge a branch, squash-merge a PR, or push directly to the default branch.** You may create branches, push to feature branches, and create PRs. When work is ready to merge, ask the user to merge. This rule has no exceptions.
