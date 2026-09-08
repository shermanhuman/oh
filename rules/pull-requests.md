---
activation: always
---

# Pull Request Rules

Follow this order:

1. **Bump the version** using the `release` skill and `version-bump.md`. An adequate bump already in this PR satisfies the rule.
2. **Open with mise-managed gh.** Resolve the actual default branch, push the feature branch, and write the exact description to a body file:

```bash
mise exec -- gh pr create --title "type: short description" --body-file /tmp/pr-body.md --base <default-branch> --head <branch>
```

Describe the final change, migration, and checks actually run. Update the existing PR when continuing the same work.

**Merging is a human task. Never merge, squash-merge, or push directly to the default branch. No exceptions.** Creating branches, pushing feature branches, and creating PRs are allowed. When ready, ask the user to merge.
