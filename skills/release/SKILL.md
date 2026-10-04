---
name: release
description: Prepares a version bump or release from the repository's actual version source (herd.json, mix.exs, VERSION, tags) and publishes only when asked. Use when bumping a version, preparing a PR's version change, or when the user asks to tag, release or publish.
---

# Version and release preparation

Identify the repository and requested action first. A **bump** changes version metadata and relevant documentation; it does not publish. A **release** follows the repository's established release mechanism for the requested version. Existing user authorization persists; ask only for a consequential choice or action outside that authorization.

## Find the source of truth

Inspect `herd.json`, `VERSION`, `mix.exs`, package metadata, build scripts, tags, and `.github/workflows/`. More than one file can describe one product; do not ask which to release solely because multiple signals exist. Ask only when there are genuinely separate products and the target is unclear.

- Herds: update top-level `herd.json.version`. The version-check workflow compares it with the PR base and requires a strictly greater semver. Herd consumers read `herd.json`; no tag is needed for a herd bump. A conventional bump commit is `chore: bump X.Y.Z → X.Y.Z+1`, or include the bump in the scoped feature commit.
- Elixir: update the actual application version in `mix.exs` or its configured source.
- Go: `go.mod`'s Go directive is not the product version. Honor `VERSION` or equivalent when present; otherwise inspect tag/build-flag conventions. With tag-only versioning, record the intended version in the PR instead of creating a publishing tag for a bump-only task.

Use the requested semver level. Without one, infer patch for fixes, minor for compatible features, and major for breaking changes, subject to the project's pre-1.0 policy. Compare with the PR base and existing edits to avoid multiple bumps for the same PR. Do not reset a larger intentional bump.

## Prepare

1. Inspect `git status --short`, the current feature branch, the PR base, and the current version source. Keep unrelated edits intact: a dirty tree is normal during feature preparation, not a reason to discard changes or force a clean-tree approval. Work on the appropriate feature branch; do not switch to main just to bump a version.
2. Compute the requested semver bump (when preparing a PR, do this after the work is tested and reviewed, as the `pull-requests` skill orders it): major `X+1.0.0`, minor `X.Y+1.0`, patch `X.Y.Z+1`. For PR preparation, a version already increased appropriately over the base is sufficient.
3. Edit `herd.json.version`, `mix.exs`'s application version, `VERSION`, or the repository's actual authoritative source; synchronize required copies.
4. Validate: Go uses `mise exec -- go test ./...`; Elixir uses `mise exec -- mix precommit` when defined, otherwise `mise exec -- mix test` and `mise exec -- mix compile --warnings-as-errors`. For a herd, validate `herd.json`, skill frontmatter, resource links, and `mise exec -- promptherder check` in a fixture with that herd installed. Run configured repository checks too, and reuse already-valid checks when no affected code changed. If a required check is unavailable, report the exact blocker instead of claiming it passed.
5. For a bump-only request, stop here and report the old/new version and changed files. For a requested PR, follow the `pull-requests` skill; do not tag in this step.

## Publish when requested

Inspect actual release automation before creating tags: some repositories tag from VERSION after a merge, others publish on a manually pushed tag. Do not add a second trigger or assume `.goreleaser.yml` proves a CI trigger exists. If automation creates tags from VERSION, use that workflow instead of creating a duplicate tag.

1. Verify the exact reviewed commit, version, required checks, and destination, and that the tag does not already exist. Never include unrelated uncommitted changes in a release commit.
2. For a tag-driven release, create `git tag vX.Y.Z <commit>` and push that exact tag. Do not push main or merge a PR; those are the user's steps.
3. Track the specific release/tag workflow and commit, not merely the newest CI run: `mise exec -- gh run list --commit <sha>`, then `mise exec -- gh run view <run-id>`. For a GitHub release, verify `mise exec -- gh release view vX.Y.Z`.
4. Report previous/new version, commit/tag, CI result, and artifact URL. Report a failed or pending publication honestly; do not substitute the newest unrelated successful run.

A release does not automatically authorize production rollout, secret rotation, or database migration. Leave those actions to the repository's deployment process and the user's requested scope.

## Project-specific release checks

### Phoenix / Elixir

Read the application version from `project/0` in `mix.exs` or the source it references. Apps using `@version Mix.Project.config()[:version]` bake the version at compile time: rebuild after the bump so the UI/footer is updated. Inspect whether CI deploys on a branch, a tag, or a manual trigger; a branch-triggered deployment is not itself a broken tag workflow.

When the app uses database migrations, every release runs the migration procedure before the app restarts: read [references/phoenix-migrations.md](references/phoenix-migrations.md) and follow it exactly.

### Go

Check `.goreleaser.yml` or `.goreleaser.yaml`, then the actual workflow. For repositories declaring `main.Version`, `main.Commit`, and `main.BuildDate`, the GoReleaser convention is:

```yaml
ldflags:
  - -X main.Version={{.Version}}
  - -X main.Commit={{.ShortCommit}}
  - -X main.BuildDate={{.Date}}
```

Use the symbols the application actually declares. If a released binary shows `dev`, inspect the build's `ldflags` and version source. When `VERSION` is tracked, update it; do not assume every Go project versions only through tags.

## Release summary

Report this table after preparation or publication; use `Not requested` for a tag or publication check that did not run.

| Field | Value |
|---|---|
| Project / type | name; herd, Elixir, or Go |
| Previous → new | vX.Y.Z → vX.Y.Z |
| Commit / tag | exact SHA; tag or Not requested |
| Validation / CI | passed, failed, pending, or blocked with reason |
| Artifact | release URL or prepared version-file path |
