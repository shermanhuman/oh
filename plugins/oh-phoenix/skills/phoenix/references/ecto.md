# Ecto: changesets, transactions and queries

Verified against Ecto 3.14 docs. Migrations are in [migrations.md](migrations.md).

## Contents

- [Changesets](#changesets)
- [Validations and constraints](#validations-and-constraints)
- [Transactions: Repo.transact and Ecto.Multi](#transactions-repotransact-and-ectomulti)
- [Preloads and N+1](#preloads-and-n1)
- [Queries live in contexts](#queries-live-in-contexts)
- [Sources](#sources)

## Changesets

- Use `cast/4` for external input such as form or API params. It casts types and drops fields that aren't in the permitted list, so never permit fields the user shouldn't set (owner ids, roles, flags).
- Use `change/2` for internal data you already trust.
- Write one changeset per use case. Each one says which fields that operation may change and what it requires.

```elixir
def registration_changeset(user, attrs) do
  user
  |> cast(attrs, [:email, :password])
  |> validate_required([:email, :password])
  |> validate_format(:email, ~r/^[^@\s]+@[^@\s]+$/)
  |> validate_length(:password, min: 12)
  |> unique_constraint(:email)
end

def profile_changeset(user, attrs) do
  user
  |> cast(attrs, [:name, :bio])
  |> validate_length(:bio, max: 500)
end
```

- Set ownership with `put_change/3` from trusted data, not from params. Phoenix 1.8 generated changesets take the scope and do this: `put_change(:user_id, scope.user.id)`.

## Validations and constraints

- Validations (`validate_*`) run in memory, immediately, before anything touches the database.
- Constraints (`unique_constraint/3`, `foreign_key_constraint/3`, `check_constraint/3`, `assoc_constraint/3`, `exclusion_constraint/3`) rely on the database. That makes them safe under concurrency. They are checked only on insert or update, and only if all validations passed.
- A constraint call only maps a database error to a changeset error. The actual constraint must exist in a migration. Without the call, the violation raises instead of returning `{:error, changeset}`.
- `unsafe_validate_unique/4` gives early feedback (for example on `phx-change`) but can race. Keep `unique_constraint/3` and a unique index as the guarantee.

## Transactions: Repo.transact and Ecto.Multi

Ecto 3.13 added `Repo.transact/2`. The docs now mark `Repo.transaction/2` as deprecated in its favour, and Phoenix 1.8 generators use `transact`.

The function must return `{:ok, value}` to commit or `{:error, reason}` to roll back. It pairs naturally with `with`:

```elixir
def transfer(scope, from, to, amount) do
  Repo.transact(fn ->
    with {:ok, from} <- debit(scope, from, amount),
         {:ok, to} <- credit(scope, to, amount) do
      {:ok, {from, to}}
    end
  end)
end
```

- Exceptions roll back and re-raise. `Repo.rollback/1` exits early with `{:error, value}`.
- After a failed statement, the database aborts the transaction, so any further query in it raises. Don't try to "recover" inside the same transaction.
- Avoid nesting. An inner failure aborts the whole outer transaction. Compose steps with `with` or `Ecto.Multi` instead.

`Ecto.Multi` builds the steps as data. Each step is named, and on failure you learn which step failed:

```elixir
Multi.new()
|> Multi.update(:account, Account.password_reset_changeset(account, params))
|> Multi.insert(:log, Log.password_reset_changeset(account, params))
|> Multi.delete_all(:sessions, Ecto.assoc(account, :sessions))
|> Repo.transact()
|> case do
  {:ok, %{account: account}} -> {:ok, account}
  {:error, _step, changeset, _changes_so_far} -> {:error, changeset}
end
```

- Use `Multi.run/3` for steps that depend on earlier results (`fn repo, changes -> ... end`).
- Building a Multi in a pure function makes it testable without a database (`Multi.to_list/1`).
- A transaction holds a database connection and its row locks until it ends. Keeping slow external calls (HTTP, email) outside it keeps both short.

## Preloads and N+1

Loading associations one parent at a time in a loop, in the template or in a component, issues N+1 queries. Preload in the context query instead.

```elixir
# separate queries, one per association (parallel outside a transaction)
Repo.all(from p in Post, preload: [:author, comments: :likes])

# join preload: one query, use when you already join to filter
Repo.all(
  from p in Post,
    join: c in assoc(p, :comments),
    where: c.published_at > p.updated_at,
    preload: [comments: c]
)

# custom preload query: filter or order the association
comments = from c in Comment, order_by: c.published_at
Repo.all(from p in Post, preload: [comments: ^comments])

# after the fact, on already-loaded structs
Repo.preload(posts, :author)
```

- The docs give a default: use join preloads only when the main query already joins the association. Joins duplicate parent rows across the result, while separate preload queries can run in parallel.
- `Repo.preload/3` skips associations that are already loaded. Pass `force: true` to reload.
- Accessing an association that wasn't preloaded gives `%Ecto.Association.NotLoaded{}`. That is a signal to preload in the context, not to query from the web layer.

## Queries live in contexts

- Build queries in the context or in schema-level query helpers that the context composes. LiveViews and controllers call named context functions.
- `Repo.all_by/3` (Ecto 3.13+) shortens simple filtered lists: `Repo.all_by(Post, author_id: id)`.
- Scope every query that returns user-owned data. Phoenix 1.8 generated code uses `Repo.all_by(Post, user_id: scope.user.id)` and `Repo.get_by!(Post, id: id, user_id: scope.user.id)`.
- Select only what you need for large lists (`select: map(p, [:id, :title])`), and paginate with keyset conditions (`where: p.id > ^last_id`, `order_by`, `limit`) rather than large offsets.

## Sources

- https://ecto.hexdocs.pm/Ecto.Changeset.html (cast vs change, validations and constraints)
- https://ecto.hexdocs.pm/Ecto.Repo.html (transact/2, transaction/2 deprecation, preload/3, all_by/3)
- https://ecto.hexdocs.pm/Ecto.Multi.html
- https://ecto.hexdocs.pm/Ecto.Query.html (preload/3, joins vs separate queries)
- https://ecto.hexdocs.pm/changelog.html (3.13: transact/2, all_by/3)
- https://phoenix.hexdocs.pm/changelog.html (1.8 generators use Repo.transact/2)
- https://github.com/phoenixframework/phoenix/blob/v1.8.15/priv/templates/phx.gen.context/schema_access_scope.ex.eex
- https://github.com/phoenixframework/phoenix/blob/v1.8.15/priv/templates/phx.gen.schema/schema.ex.eex
