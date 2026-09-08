---
activation: always
---

# Version Bump Rule

**Bump before opening a PR, regardless of CI gates.** For repositories with `herd.json`, `mix.exs`, or `go.mod`, use the `release` skill and run tool commands through mise. Default to patch for fixes/docs, minor for compatible features, major for breaking changes; honor the user's explicit level.

Compare with the PR base. An adequate existing bump satisfies this PR; do not bump again for each revision. Keep synchronized version files consistent. For Go, inspect `VERSION` and build/release configuration: the `go.mod` Go directive is not the product version. With tag-only versioning, record the intended version in the PR; do not create a publishing tag for a bump-only task.

A bump does not authorize tagging, releasing, merging, or deployment. Use the release skill's publication phase only when requested.
