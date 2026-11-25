---
name: release
description: This machine's specifics for version bumps and releases on top of compound-v:release — tools through mise, releasing through a GitOps repository's own path (stage, then promote, as PRs), and the migration procedure for releases deployed by hand. Use when bumping a version or releasing on this machine, before staging or promoting a release, and before any Phoenix release's migrations run.
---

# Release: this machine's specifics

The procedure is `compound-v:release`. On this machine:

- Run every tool through mise: `mise exec -- cargo test --workspace --locked`, `mise exec -- go test ./...`, `mise exec -- mix precommit` (or `mix test` and `mix compile --warnings-as-errors`), `mise exec -- gh release view vX.Y.Z`.
- **GitOps repositories** (a repository Argo CD syncs from, such as breakdown-infra): a release is the repository's own path, and its README's *Releasing* section is the procedure. In breakdown-infra:
  1. Before staging, list the migrations the release adds (the app repository's migration files changed between the image production runs and the one you stage). If one drops a column or table, or deletes data, stop: it waits for the user's yes, as a board task naming the migration. Say in the PR which migrations it carries.
  2. `scripts/stage.sh IMAGE[@SHA]` opens the staging PR. Merging it is the user's, like every merge: hand it over as a board task with the PR's link.
  3. Once Argo shows staging Synced and Healthy, check the release there (`<app>-staging.<tailnet>.ts.net`) and say what you checked.
  4. `scripts/promote.sh IMAGE` opens the production PR, which the user approves and merges. Argo deploys it and reports to the user's phone; read the result from Argo, read-only.
  5. Rollback is reverting the promotion PR, handed over the same way.

  Migrations run inside the sync, as hook Jobs pinned to the image's digest, so never run a migration Job, restart, scale or refresh by hand there. With read-only cluster access, that's the only way, and a refusal means the step is the user's or a PR's, never a different command.
- **Phoenix / Elixir:** read the version from `project/0` in `mix.exs` or the source it references. Apps that bake `@version Mix.Project.config()[:version]` need a rebuild after the bump. When the app uses database migrations and is deployed by hand (not through a GitOps repository), every release runs the migration procedure before the app restarts: read [references/phoenix-migrations.md](references/phoenix-migrations.md) and follow it exactly. A destructive migration waits for the user's yes.
- **Go with GoReleaser:** use the `ldflags` symbols the application actually declares (`-X main.Version={{.Version}}` and the like). A released binary that prints `dev` means the build's `ldflags` or version source is wrong.
