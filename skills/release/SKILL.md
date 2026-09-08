---
name: release
description: Prepare a requested version bump or release using the repository’s actual version source and publishing workflow.
---

# Version and release preparation

Identify the repository and requested action first. A **bump** changes version metadata and relevant documentation; it does not publish. A **release** follows the repository's established release mechanism for the requested version. Existing user authorization persists; ask only for a consequential choice or action outside that authorization.

## Find the source of truth

Inspect `herd.json`, `VERSION`, `mix.exs`, package metadata, build scripts, tags, and `.github/workflows/`. More than one file can describe one product; do not ask which to release solely because multiple signals exist. Ask only when there are genuinely separate products and the target is unclear.

- Herds: update top-level `herd.json.version`; inspect the repository's version-check gate.
- Elixir: update the actual application version in `mix.exs` or its configured source.
- Go: `go.mod` is not an application version file. Honor `VERSION` or equivalent when present; otherwise inspect tag/build-flag conventions. A bump-only request in a tag-only project may need a proposed next version rather than creating a publishing tag.

Use the requested semver level. Without one, infer patch for fixes, minor for compatible features, and major for breaking changes, subject to the project's pre-1.0 policy. Compare with the PR base and existing edits to avoid multiple bumps for the same PR. Do not reset a larger intentional bump.

## Prepare

Inspect the working tree and preserve unrelated edits. A dirty tree is normal during feature preparation, not a reason to discard changes or force a clean-tree approval. Work on the appropriate feature branch; do not switch to main just to bump a version. Edit the authoritative metadata and any required synchronized copies. Run applicable validation and reuse already-valid checks when no affected code changed.

Stop here for a bump-only request and report the old/new version and changed files. If the user requested a PR, continue through the PR workflow without tagging or publishing.

## Publish when requested

Inspect actual release automation before creating tags: some repositories tag from VERSION after a merge, others publish on a manually pushed tag. Do not add a second trigger or assume `.goreleaser.yml` proves a CI trigger exists. Verify the exact commit, version, required checks, and destination before the authorized publish step. Never include unrelated uncommitted changes in a release commit.

Track the specific release/tag workflow and commit, not merely the newest CI run. Report the exact artifact/tag and checks. A release does not automatically authorize production rollout, secret rotation, or database migration. Leave those actions to the repository's deployment process and the user's requested scope.
