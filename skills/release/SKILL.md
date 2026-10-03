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

## Required command sequence

Use mise for all managed CLI operations, including GitHub. Do not substitute another package manager or a different GitHub integration merely because it is available.

1. Inspect `git status --short`, the current feature branch, the PR base, and the current version source. Keep unrelated edits intact.
2. Compute the requested semver bump: major `X+1.0.0`, minor `X.Y+1.0`, patch `X.Y.Z+1`. For PR preparation, a version already increased appropriately over the base is sufficient.
3. Edit `herd.json.version`, `mix.exs`'s application version, `VERSION`, or the repository's actual authoritative source; synchronize required copies.
4. Validate: Go uses `mise exec -- go test ./...`; Elixir uses `mise exec -- mix precommit` when defined, otherwise `mise exec -- mix test` and `mise exec -- mix compile --warnings-as-errors`. For a herd, validate `herd.json`, skill frontmatter, resource links, and `mise exec -- promptherder check` in a fixture with that herd installed. Run configured repository checks too.
5. For a requested PR, commit the scoped changes, push the feature branch, and run `mise exec -- gh pr create --base <default-branch> --head <feature-branch> --title '<title>' --body-file <body-file>`. Update the existing PR when one already exists. Do not tag as part of this step.

If mise cannot supply a particular tool, follow the mise policy's documented fallback; do not silently choose another installer. If a required check is unavailable, report the exact blocker instead of claiming it passed.

## Prepare

Inspect the working tree and preserve unrelated edits. A dirty tree is normal during feature preparation, not a reason to discard changes or force a clean-tree approval. Work on the appropriate feature branch; do not switch to main just to bump a version. Edit the authoritative metadata and any required synchronized copies. Run applicable validation and reuse already-valid checks when no affected code changed.

Stop here for a bump-only request and report the old/new version and changed files. If the user requested a PR, continue through the PR workflow without tagging or publishing.

## Publish when requested

Inspect actual release automation before creating tags: some repositories tag from VERSION after a merge, others publish on a manually pushed tag. Do not add a second trigger or assume `.goreleaser.yml` proves a CI trigger exists. Verify the exact commit, version, required checks, and destination before the authorized publish step. Never include unrelated uncommitted changes in a release commit.

Track the specific release/tag workflow and commit, not merely the newest CI run. Report the exact artifact/tag and checks. A release does not automatically authorize production rollout, secret rotation, or database migration. Leave those actions to the repository's deployment process and the user's requested scope.

## Publication checklist

For an explicitly requested tag-driven release, verify the exact reviewed commit and that the tag does not already exist, then create `git tag vX.Y.Z <commit>` and push that exact tag. Do not push main or merge a PR; those are human tasks under this repository policy. If automation creates tags from VERSION, use that workflow instead of creating a duplicate tag.

Use `mise exec -- gh run list --commit <sha>` to find the matching run and `mise exec -- gh run view <run-id>` to inspect it. For a GitHub release, verify `mise exec -- gh release view vX.Y.Z`. Report previous/new version, commit/tag, CI result, and artifact URL. Report a failed or pending publication honestly; do not substitute the newest unrelated successful run.

## Project-specific release checks

### Phoenix / Elixir

Read the application version from `project/0` in `mix.exs` or the source it references. Apps using `@version Mix.Project.config()[:version]` bake the version at compile time: rebuild after the bump so the UI/footer is updated. Inspect whether CI deploys on a branch, a tag, or a manual trigger; a branch-triggered deployment is not itself a broken tag workflow.

When the requested release includes Ecto migrations, include the repository's migration procedure in the handoff, run it before the app restarts, and never `kubectl create -f` a whole manifest file: such a file can hold other apps' Jobs or an existing NetworkPolicy, and a Job left on `:latest` can pull the previous release, find nothing to migrate and exit 0. In repositories that provide `scripts/run-migration.sh` (breakdown-infra), the procedure is two steps. First `digest=$(scripts/run-migration.sh <app-name>)`: fail-stop, it fetches origin, waits until the registry serves the new build, creates only the Job whose `generateName` is `<app-name>-migrate-` (from the app's migration manifest on `origin/main`), pinned to that digest, waits for it, saves its log before its `ttlSecondsAfterFinished` deletes it, and refuses a log saying "Migrations already up". If it fails (non-zero exit, empty `$digest`), **stop: do not run `deploy.sh`; the release is not migrated**, and report its error and saved log. Proceed only when the saved log lists the release's new versions as applied. Then `EXPECT_DIGEST="$digest" scripts/deploy.sh <app-name>` (never `--sync` for an app release): it restarts only onto exactly that digest and refuses an empty or different one before any restart; then the repository's pending-migration check. Run `kubectl` and these scripts (which call `kubectl`) through `mise exec --` when the shell is not mise-activated; in breakdown-infra prefix `MISE_EXEC_AUTO_INSTALL=false`. Follow the repository's README ("Running Ecto migrations") where it differs. Run these only as part of an authorized deployment, with the actual context and namespace checked. Prefer the connected Kubernetes MCP for supported operations under the mise rule.

### Go

Check `.goreleaser.yml` or `.goreleaser.yaml`, then the actual workflow. For repositories declaring `main.Version`, `main.Commit`, and `main.BuildDate`, the GoReleaser convention is:

```yaml
ldflags:
  - -X main.Version={{.Version}}
  - -X main.Commit={{.ShortCommit}}
  - -X main.BuildDate={{.Date}}
```

Use the symbols the application actually declares. If a released binary shows `dev`, inspect the build's `ldflags` and version source. When `VERSION` is tracked, update it; do not assume every Go project versions only through tags.

### Promptherder herds

Bump top-level `herd.json.version` before a PR. The version-check workflow compares it with the PR base and requires a strictly greater semver. Herd consumers read `herd.json`; no tag is needed for a herd version bump. A conventional bump commit is `chore: bump X.Y.Z → X.Y.Z+1`, or include the bump in the scoped feature commit.

## Release summary

Report this table after preparation or publication; use `Not requested` for a tag or publication check that did not run.

| Field | Value |
|---|---|
| Project / type | name; herd, Elixir, or Go |
| Previous → new | vX.Y.Z → vX.Y.Z |
| Commit / tag | exact SHA; tag or Not requested |
| Validation / CI | passed, failed, pending, or blocked with reason |
| Artifact | release URL or prepared version-file path |
