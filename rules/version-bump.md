---
trigger: always_on
---

# Version Bump Rule

- **Bump version before opening a PR.** If the repo contains `herd.json`, `mix.exs`, or `go.mod`, use the `release` skill to bump the version before creating a pull request. Default to `patch` for minor changes. The CI version-check gate will reject PRs without a version bump.
