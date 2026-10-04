# Safe migrations on live tables

Based on the Safe Ecto Migrations guides by David Bernheisel, now part of the ecto_sql 3.14 docs. The examples are for PostgreSQL. The guide notes MySQL and MariaDB differences where they matter.

## Contents

- [Principles](#principles)
- [Lock and statement timeouts](#lock-and-statement-timeouts)
- [Indexes](#indexes)
- [Foreign keys and check constraints](#foreign-keys-and-check-constraints)
- [NOT NULL on an existing column](#not-null-on-an-existing-column)
- [Columns with defaults](#columns-with-defaults)
- [Changing types, removing and renaming](#changing-types-removing-and-renaming)
- [Backfills are data migrations](#backfills-are-data-migrations)
- [Sources](#sources)

## Principles

- Scale is the deciding factor. A lock that takes milliseconds on a million rows can take seconds on a hundred million rows and cause timeouts. Err on the side of safety and benchmark on realistic data.
- Running instances read the schema they were deployed with. Any change that breaks the old code (drop, rename, type change) needs the code to stop depending on the old shape first, which means more than one deploy.
- Keep each risky operation in its own migration. Split steps that take different locks: create, then validate.
- `Ecto.Migration.modify/3` always restates the column type, which can rewrite the table. Change only a default or a nullability with `execute/2` and raw SQL.

## Lock and statement timeouts

DDL waits for an exclusive lock, and while it waits every query queued behind it waits too. A `lock_timeout` makes an unsafe migration fail fast instead of stalling traffic.

```elixir
defmodule MyApp.Migration do
  defmacro __using__(_) do
    quote do
      use Ecto.Migration

      def after_begin do
        execute "SET LOCAL lock_timeout TO '5s'", "SET LOCAL lock_timeout TO '10s'"
      end
    end
  end
end

# config/config.exs, so mix ecto.gen.migration uses it
config :ecto_sql, migration_module: MyApp.Migration
```

- `after_begin/0` and `before_commit/0` run only inside the migration transaction. They are skipped when `@disable_ddl_transaction true` is set.
- Alternatives: `ALTER ROLE migrator SET lock_timeout = '10s'` for a dedicated migration role, and a role-level `statement_timeout` (for example `'10m'`) as a ceiling on runaway statements. Postgres notes that a `lock_timeout` equal to or larger than `statement_timeout` is pointless.

## Indexes

Plain `CREATE INDEX` blocks writes, and plain `DROP INDEX` blocks reads and writes. Use `CONCURRENTLY`, which cannot run inside a transaction.

```elixir
# Preferred: advisory-lock migration locking (ecto_sql 3.9+), in config
config :my_app, MyApp.Repo, migration_lock: :pg_advisory_lock

defmodule MyApp.Repo.Migrations.AddPostsSlugIndex do
  use Ecto.Migration
  @disable_ddl_transaction true

  def change do
    create index("posts", [:slug], concurrently: true)
  end
end
```

- Without advisory locks, also set `@disable_migration_lock true`. The default table lock uses another transaction. The trade-off is that several nodes could run the same migration at once, so run migrations from a single node or job.
- In dev, `Phoenix.Ecto.CheckRepoStatus` checks for pending migrations without a migration lock by default (`migration_lock: false`), so web requests don't wait on the advisory lock. Keep that default.
- Put nothing else in a concurrent-index migration. Without the DDL transaction, a failure part-way leaves the earlier steps applied.
- Drop indexes the same way: `drop index("posts", [:slug], concurrently: true)`.

## Foreign keys and check constraints

Adding a foreign key blocks writes on both tables. Adding a validated check constraint scans the whole table under lock. Create the constraint unvalidated so it applies to new writes, then validate it in a separate migration. Validation takes a lighter lock that doesn't block reads or writes.

```elixir
# migration 1
alter table("posts") do
  add :group_id, references("groups", validate: false)
end
create constraint("products", :price_must_be_positive, check: "price > 0", validate: false)

# migration 2 (can ship in the same deploy)
execute "ALTER TABLE posts VALIDATE CONSTRAINT posts_group_id_fkey", ""
execute "ALTER TABLE products VALIDATE CONSTRAINT price_must_be_positive", ""
```

Ecto names a reference `"#{table}_#{column}_fkey"` unless you pass `name:`. Check the name in the database before writing the `VALIDATE` statement. The down direction is `""` because there is no "unvalidate".

## NOT NULL on an existing column

`modify :col, :type, null: false` scans the table under lock. Do it in steps instead:

1. Deploy 1: `create constraint("products", :active_not_null, check: "active IS NOT NULL", validate: false)`. New and updated rows are now checked.
2. Backfill existing NULLs with a data migration (see below).
3. Deploy 2: validate, then set NOT NULL. Postgres skips the scan when a valid check constraint already proves there are no NULLs.

```elixir
def change do
  execute "ALTER TABLE products VALIDATE CONSTRAINT active_not_null", ""
  execute "ALTER TABLE products ALTER COLUMN active SET NOT NULL",
          "ALTER TABLE products ALTER COLUMN active DROP NOT NULL"
  drop constraint("products", :active_not_null)
end
```

## Columns with defaults

- On PostgreSQL 11+ (and MySQL 8.0.12+, MariaDB 10.3.2+), adding a column with a constant default is usually a fast metadata change.
- A volatile default such as `fragment("now()")` still rewrites the table. For volatile defaults or older versions, add the column without a default, then set the default in a second migration:

```elixir
alter table("comments"), do: add(:approved, :boolean)

execute "ALTER TABLE comments ALTER COLUMN approved SET DEFAULT false",
        "ALTER TABLE comments ALTER COLUMN approved DROP DEFAULT"
```

- With that approach, existing rows stay NULL until they are updated or backfilled. Ecto's schema `default:` applies only on the application side.
- Change an existing default with `execute "ALTER TABLE ... ALTER COLUMN ... SET DEFAULT ..."` rather than `modify/3`. Rows already written keep their old value.
- Use `:jsonb` rather than `:json`. Postgres has no equality operator for `json`, which breaks `SELECT DISTINCT`.

## Changing types, removing and renaming

- **Remove a column:** deploy 1 removes the field from the Ecto schema and all code. Deploy 2 drops the column. Otherwise running nodes fail when loading structs.
- **Rename a column:** prefer not to. Rename the schema field and point it at the old column with `field :precipitation, :float, source: :prcp`. For a real rename: add the new column, write to both, backfill, move reads, drop the old column from the schema, then drop the old column.
- **Rename a table:** prefer renaming the schema module only and keeping the table name. Otherwise use the same phased approach.
- **Change a type:** most changes rewrite the table. Postgres can skip the rewrite for a few, such as widening `varchar` or `varchar` to `text`. For everything else, use the phased new-column approach.

## Backfills are data migrations

Don't backfill inside a schema migration. In a transaction it holds row locks for the whole run. Unbatched, it can saturate the database. It also tends to reference application schemas that change later and break the migration.

The guide's four keys are: run outside a transaction, batch, throttle, and make it resumable.

- Keep data migrations in their own path and run them on purpose: `mix ecto.gen.migration --migrations-path=priv/repo/data_migrations backfill_posts`. In releases, add a release task that calls `Ecto.Migrator.run/4` with that path.
- Snapshot the schema. Query the table by name (`from r in "posts"`) or define a small schema inside the migration, rather than using application schemas.
- Use keyset pagination, not OFFSET, and sleep between batches.

```elixir
defmodule MyApp.Repo.DataMigrations.BackfillApproved do
  use Ecto.Migration
  import Ecto.Query

  @disable_ddl_transaction true
  @disable_migration_lock true
  @batch_size 1000
  @throttle_ms 100

  def up, do: backfill(0)
  def down, do: :ok

  defp backfill(last_id) do
    ids =
      repo().all(
        from(p in "posts",
          select: p.id,
          where: is_nil(p.approved) and p.id > ^last_id,
          order_by: [asc: p.id],
          limit: @batch_size
        )
      )

    case ids do
      [] ->
        :ok

      ids ->
        repo().update_all(from(p in "posts", where: p.id in ^ids), set: [approved: false])
        Process.sleep(@throttle_ms)
        backfill(List.last(ids))
    end
  end
end
```

The `is_nil(approved)` condition makes reruns pick up where they stopped. For updates with no such marker, the guide copies the target ids into a regular tracking table first and deletes each batch's ids as it goes. It avoids a `TEMP` table because that is lost if the session ends, and the progress with it.

## Sources

- https://ecto-sql.hexdocs.pm/safe_migrations.html (Safe Ecto Migrations, ecto_sql 3.14)
- https://ecto-sql.hexdocs.pm/migration_anatomy.html (migration lock, DDL transaction, lock_timeout, statement_timeout)
- https://ecto-sql.hexdocs.pm/backfilling_data.html (batched, throttled data migrations)
- https://ecto-sql.hexdocs.pm/Ecto.Migration.html (transaction callbacks, concurrent indexes, constraint validate: false)
- https://ecto-sql.hexdocs.pm/Ecto.Adapters.Postgres.html (migration_lock options)
- https://github.com/fly-apps/safe-ecto-migrations (original guide; also published at https://fly.io/phoenix-files/safe-ecto-migrations/)
