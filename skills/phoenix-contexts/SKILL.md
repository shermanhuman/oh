---
name: phoenix-contexts
description: Enforces the Phoenix context boundary pattern — all Repo calls and Ecto.Query usage belong in context modules, never in LiveViews or controllers. Use when building, reviewing, or refactoring Phoenix applications.
---

# Phoenix Context Boundary

**The rule:** `Repo` and `Ecto.Query` never appear in the web layer. All data access goes through context modules.

| Layer          | Owns                                       | Never contains                  |
| -------------- | ------------------------------------------ | ------------------------------- |
| `lib/app_web/` | Routing, templates, socket assigns         | `Repo.*`, `Ecto.Query`, `from(` |
| `lib/app/`     | Contexts, schemas, queries, business logic | `conn`, `socket`, templates     |

## Detect

```bash
grep -rn "import Ecto.Query\|Repo\." lib/*_web/
```

Any results are violations.

## Fix

Move the query into the relevant context module. The LiveView calls the context function instead.

```elixir
# ❌ Query in LiveView
defp unread_count, do: from(a in Alert, where: is_nil(a.read_at)) |> Repo.one()

# ✅ Query in context, LiveView calls it
# lib/app/alerts.ex
def unread_count, do: from(a in Alert, where: is_nil(a.read_at)) |> Repo.one()

# lib/app_web/live/dashboard_live.ex
assign(socket, :unread, Alerts.unread_count())
```

If no existing context fits, create a new one. Phoenix contexts are cheap.

## Why

- **Testable** — context functions test without mounting a LiveView
- **Reusable** — same query callable from LiveViews, controllers, workers, Mix tasks
- **Discoverable** — one place to find and change a query
