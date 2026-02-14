---
name: release
description: Semver release workflow — bump version, tag, push, verify CI. Use when releasing, bumping version, updating version, or when the user says 'release', 'bump', 'major', 'minor', 'patch', 'update version', 'new version', 'cut a release', 'tag', or 'goreleaser'.
---

# Release Skill

Handles semver releases for Go and Phoenix/Elixir projects. Detects the project type automatically and follows the appropriate workflow.

## Detect Project Type

| Signal           | Type           |
| ---------------- | -------------- |
| `mix.exs` exists | Phoenix/Elixir |
| `go.mod` exists  | Go             |

If both exist, ask the user which to release.

## Pre-release Checklist

Before bumping, verify:

1. **Working tree is clean** — `git status --porcelain` should be empty. If not, warn the user.
2. **On the correct branch** — check with `git branch --show-current`. Typically `main`. Warn if on a different branch.
3. **Tests pass** — run `mix precommit` (Elixir, per project rules) or `go test ./...` (Go).
4. **Current version** — read and display the current version so the user confirms the bump.

## Version Bump

### Determine Bump Type

If the user said "bump" without specifying, ask:

> Bump type? `major` (breaking changes), `minor` (new features), `patch` (fixes)

Apply semver rules: given `X.Y.Z`:

- `major` → `X+1.0.0`
- `minor` → `X.Y+1.0`
- `patch` → `X.Y.Z+1`

---

### Phoenix/Elixir

**Version location:** `mix.exs` → `version: "X.Y.Z"` in the `project/0` function.

**Steps:**

1. Read current version from `mix.exs`
2. Compute new version based on bump type
3. Update `mix.exs` with new version string
4. Run `mix compile` to verify
5. Commit: `chore: bump version to vX.Y.Z`
6. Tag: `git tag vX.Y.Z`
7. Push: `git push origin $(git branch --show-current) && git push origin vX.Y.Z`
8. Verify CI: `gh run list --limit 1` — confirm the workflow triggered

**CI trigger:** The GitHub Actions workflow should trigger on tag pushes (`on: push: tags: ['v*']`). If the current workflow triggers on `push: branches: [main]` instead, **warn the user** that the CI won't trigger on tags and suggest updating the workflow.

**Version display:** Phoenix apps using a `Meta` module (pattern: `@version Mix.Project.config()[:version]`) will automatically pick up the new version at compile time. The Docker build bakes it into the release.

**Migration note:** If the release includes Ecto migrations, remind the user to run the migration job after deployment:

```
kubectl create -f apps/<app-name>/migration-job.yaml
```

---

### Go

**Version location:** Set via `ldflags` at build time. The version comes from the git tag — no file to edit.

**Steps:**

1. Read current version: `git describe --tags --abbrev=0` (or check GitHub releases)
2. Compute new version based on bump type
3. Commit any pending changes first (if needed)
4. Tag: `git tag vX.Y.Z`
5. Push: `git push origin $(git branch --show-current) && git push origin vX.Y.Z`
6. Verify CI: `gh run list --limit 1` — confirm the release workflow triggered

**GoReleaser detection:** Check for `.goreleaser.yml` or `.goreleaser.yaml` in the repo root. If present, the CI uses GoReleaser. If absent, check `.github/workflows/` for the release mechanism — it may use a custom workflow or `go build` directly.

**GoReleaser convention:** Go projects use `.goreleaser.yml` with `ldflags` to inject:

- `-X main.Version={{.Version}}`
- `-X main.Commit={{.ShortCommit}}`
- `-X main.BuildDate={{.Date}}`

No file edits needed — the git tag IS the version.

---

## Post-release Verification

After pushing:

1. **Check CI status:** `gh run list --repo <owner/repo> --limit 3 --json status,conclusion,displayTitle`
2. **Wait for completion** if still running, then report success/failure
3. **For Phoenix/Elixir:** Remind about pod rollout and migration if applicable:
   - `kubectl rollout restart deployment/<app-name>` (if using `:latest` tag)
   - `kubectl create -f apps/<app-name>/migration-job.yaml` (if migrations exist)
   - `kubectl rollout status deployment/<app-name> --timeout=120s`
4. **For Go:** Check GitHub Releases page: `gh release view vX.Y.Z --repo <owner/repo>`

## Output Format

```
## Release Summary

| Field | Value |
|---|---|
| Project | <name> |
| Type | Phoenix/Elixir or Go |
| Previous | vX.Y.Z |
| New | vX.Y.Z |
| Tag | vX.Y.Z |
| CI | ✅ Passed / ⏳ Running / ❌ Failed |
```

## Common Issues

- **CI doesn't trigger on tags:** Check that the workflow has `on: push: tags: ['v*']`, not just `on: push: branches: [main]`
- **Elixir version not updated in footer:** The `Meta` module reads `@version` at compile time — the Docker build must happen AFTER the version bump commit
- **Go version shows "dev":** The `ldflags` aren't being set — check `.goreleaser.yml` or the build command
- **ArgoCD doesn't pick up new image:** If deployment.yaml uses `:latest`, ArgoCD won't see a change. Either pin to the semver tag or run `kubectl rollout restart`
