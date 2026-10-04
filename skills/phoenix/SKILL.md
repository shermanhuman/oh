---
name: phoenix
description: Phoenix framework patterns for Phoenix 1.8, LiveView 1.x and Ecto 3.13+. Covers context boundaries and scopes, LiveView (streams, async assigns, function components, forms, navigation, JS commands, PubSub), Ecto changesets, transactions and preloads, safe migrations on live tables, and testing with ConnCase, DataCase and Phoenix.LiveViewTest. Use when building, reviewing or refactoring Phoenix apps, including contexts, LiveViews, Ecto queries, changesets, migrations or tests.
---

# Phoenix

## The two-sided split

The most important pattern in Phoenix:

| Contexts                                                           | Web layer                                                                 |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| **Business logic**: database queries, validations, business rules | **Web interface**: routes, controllers, LiveViews, templates, components |
| No HTML, no HTTP, no web concerns                                  | Calls into contexts but never contains business logic itself              |

The web layer asks contexts for data. Contexts know nothing about the web.

### The violation

When the split breaks, you'll find `Repo` calls or `Ecto.Query` imports in LiveViews or controllers. Move those into the appropriate context module.

```elixir
# ❌ Business logic in the web layer
defp queue_depth do
  Oban.Job |> where([j], j.state == "available") |> Repo.one()
end

# ✅ Web layer calls the context
assign(socket, :queue_depth, Jobs.queue_depth())
```

## Top rules

- Keep `Repo` and query building in contexts. Preload there too, so callers get the data they render and you avoid N+1 queries.
- In Phoenix 1.8 generated code, context functions take the scope first (`list_posts(scope)`) and filter by it. Keep that shape: it makes data access scoped by default.
- Broadcast PubSub messages from the context after a successful write. In LiveViews, subscribe inside `if connected?(socket)`, because `mount/3` runs once for the static render and again on connect.
- Use streams for large or growing collections. Stream items are freed from socket state after each render.
- Move slow work out of `mount/3` with `assign_async/4`, `stream_async/4` or `start_async/4`. Copy the values you need into variables first rather than capturing `socket` in the function.
- Load data in `mount/3`. Read in `handle_params/3` only the URL params that change via `patch`.
- Build forms with `to_form/2` and show errors only for inputs the user has touched (`used_input?/1`, LiveView 1.0+).
- Write one changeset per use case. Back uniqueness and integrity with database constraints plus the matching `*_constraint/3` call.
- Use `Repo.transact/2` (Ecto 3.13+) for multi-step writes. It takes a function returning `{:ok, _}` or `{:error, _}`, or an `Ecto.Multi`.
- Migrations on live tables: build indexes concurrently, add constraints with `validate: false` and validate them later, run backfills as separate batched data migrations, and drop or rename columns over several deploys.

## References

- [references/liveview.md](references/liveview.md): lifecycle, mount and handle_params, navigation, streams, async work, function components, forms, JS commands, PubSub, memory and change tracking.
- [references/ecto.md](references/ecto.md): changesets, validations and constraints, `Repo.transact/2` and `Ecto.Multi`, preloads and N+1, scoped queries.
- [references/migrations.md](references/migrations.md): safe migrations on live tables, covering lock timeouts, concurrent indexes, constraints, NOT NULL, defaults, renames and removals, and batched backfills.
- [references/architecture-testing.md](references/architecture-testing.md): contexts and scopes, generators, layouts, and tests with DataCase, ConnCase, the SQL sandbox and Phoenix.LiveViewTest.
