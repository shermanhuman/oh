---
name: release
description: This machine's specifics for version bumps and releases on top of compound-v:release — tools through mise, and the Phoenix migration procedure that every Phoenix release runs. Use when bumping a version or releasing on this machine, and before any Phoenix release's migrations run.
---

# Release: this machine's specifics

The procedure is `compound-v:release`. On this machine:

- Run every tool through mise: `mise exec -- cargo test --workspace --locked`, `mise exec -- go test ./...`, `mise exec -- mix precommit` (or `mix test` and `mix compile --warnings-as-errors`), `mise exec -- gh release view vX.Y.Z`.
- **Phoenix / Elixir:** read the version from `project/0` in `mix.exs` or the source it references. Apps that bake `@version Mix.Project.config()[:version]` need a rebuild after the bump. When the app uses database migrations, every release runs the migration procedure before the app restarts: read [references/phoenix-migrations.md](references/phoenix-migrations.md) and follow it exactly. A destructive migration waits for the user's yes.
- **Go with GoReleaser:** use the `ldflags` symbols the application actually declares (`-X main.Version={{.Version}}` and the like). A released binary that prints `dev` means the build's `ldflags` or version source is wrong.
