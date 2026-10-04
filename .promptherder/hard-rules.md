---
activation: always
---

# Hard Rules

Project-level rules that are always active when syncing inside this repository.

- **Merging is the user's step.** Don't merge or squash-merge a PR and don't push to the default branch, because each merge starts a release. Creating branches, pushing feature branches and creating PRs are fine. Merging the default branch into your own feature branch is expected; don't rebase or force-push it, so commit SHAs already posted on the PR stay valid. When work is ready to merge, ask the user to merge.
