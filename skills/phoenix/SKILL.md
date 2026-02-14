---
name: phoenix
description: Core Phoenix framework patterns — context boundaries, LiveView, Ecto, and application architecture. Use when building, reviewing, or refactoring Phoenix applications.
---

# Phoenix Two-Sided Split

The most important pattern in Phoenix:

| Contexts                                                           | Web layer                                                                 |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| **Business logic** — database queries, validations, business rules | **Web interface** — routes, controllers, LiveViews, templates, components |
| No HTML, no HTTP, no web concerns                                  | Calls into contexts but never contains business logic itself              |

The web layer asks contexts for data. Contexts know nothing about the web.

## The Violation

When the split breaks, you'll find `Repo` calls or `Ecto.Query` imports in LiveViews or controllers. Move those into the appropriate context module.

```elixir
# ❌ Business logic in the web layer
defp queue_depth do
  Oban.Job |> where([j], j.state == "available") |> Repo.one()
end

# ✅ Web layer calls the context
assign(socket, :queue_depth, Jobs.queue_depth())
```
