---
activation: always
---

# Version bumps

Every PR in a repository with `herd.json`, `mix.exs` or `go.mod` carries a version bump, even where CI doesn't check for one. Use the `release` skill: bump last, after the work is tested and reviewed, from the PR base's version; patch for fixes and docs, minor for compatible features, major for breaking changes, unless the user names a level. One bump per PR, re-applied at the same level if another PR merges first and the base reaches it. A bump never authorizes tagging, publishing, merging or deploying.
