# Phoenix release migrations (Kubernetes)

Contents: [When it applies](#when-it-applies) · [Procedure](#procedure) · [Where it runs](#where-it-runs)

## When it applies

When the app uses database migrations, every release runs the repository's migration procedure before the app restarts. That includes a release with no migrations of its own: it confirms the schema is current and pins the restart to the migrated image. Include the procedure in the handoff. Follow the repository's README where it differs.

## Procedure

1. Never `kubectl create -f` a whole manifest file. Such a file can hold other apps' Jobs or an existing NetworkPolicy, and a Job left on a moving tag such as `:latest` can pull the previous release, find nothing to migrate and exit 0.
2. Run only the migration Job, pinned to the release's image digest, wait for it, and save its log before the Job is cleaned up.
3. When the repository provides a migration script (for example `scripts/run-migration.sh` that prints the digest it migrated), use it. If it fails or prints no digest, **stop: do not restart the app; the release is not migrated**, and report the error and the saved log.
4. Proceed only when the saved log lists the release's new migration versions as applied, or reports that migrations were already up after a rerun and those versions are confirmed with a read-only query of the migrations table. For a release with no migrations of its own, "already up" is enough.
5. Restart through the repository's deploy script with the migrated digest (for example `EXPECT_DIGEST="$digest" scripts/deploy.sh <app-name>`), which must refuse to restart onto any other image.
6. Run the repository's post-restart checks.

## Where it runs

Run `kubectl` and these scripts through `mise exec --` when the shell is not mise-activated, following the repository's own mise notes. Run them only as part of an authorized deployment, with the actual context and namespace checked. Prefer the connected Kubernetes MCP for supported operations under the mise rule.
