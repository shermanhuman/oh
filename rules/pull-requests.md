---
activation: always
---
# Pull requests

When a PR is requested, prepare the scoped changes and run the required checks. Apply the version policy in `version-bump.md`; that rule is the single source of version-bump guidance. Check the actual default branch and push the feature branch before creating the PR with an available GitHub tool or `gh` (through mise when managed). Use a body file or structured argument for multiline descriptions.

Describe the final problem, resulting behavior, migration requirements, and checks actually run. Keep PR text in normal professional prose even when Grugg is active. Update an existing PR when continuing the same branch instead of creating duplicates.

By default, leave merging to the user and do not push directly to the default branch. A specific user instruction can change that preference; a generic implementation, YOLO, version-bump, or PR request cannot.
