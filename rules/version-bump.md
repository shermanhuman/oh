---
activation: always
---
# Version changes

Before a PR, inspect this repository's version source and CI/release policy. If a bump is required or requested, use `release` when installed, or the repository’s documented process, to update it once for the PR. Do not bump again merely because more fixes were added to that PR. Compare with the PR base; preserve an already adequate increase.

Use the user's explicit major/minor/patch choice. Otherwise choose according to the actual compatibility change and project policy. `go.mod` declares a module and Go version, not necessarily the application version; inspect `VERSION`, build flags, tags, and release automation. A version bump does not authorize tagging, pushing, merging, publishing, or deployment.
