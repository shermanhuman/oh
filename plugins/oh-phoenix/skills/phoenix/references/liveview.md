# LiveView

Verified against Phoenix LiveView 1.2.x docs. APIs added after 1.0 are marked with their version.

## Contents

- [Lifecycle: mount and handle_params](#lifecycle-mount-and-handle_params)
- [Navigation](#navigation)
- [Streams](#streams)
- [Async work](#async-work)
- [Function components](#function-components)
- [Forms](#forms)
- [JS commands](#js-commands)
- [PubSub](#pubsub)
- [Memory and change tracking](#memory-and-change-tracking)
- [Sources](#sources)

## Lifecycle: mount and handle_params

- `mount/3` runs twice: once for the static HTTP render and again when the websocket connects. Use `connected?(socket)` to gate stateful work such as subscriptions and timers.
- The docs say to load data in `mount/3`, since it runs once per LiveView lifecycle. Only params you expect to change through `<.link patch>` or `push_patch/2` belong in `handle_params/3`, which runs after mount and again on every patch.
- Example: on a post page with paginated comments, read `post_id` in `mount/3` and `page` in `handle_params/3`.

```elixir
def mount(%{"id" => id}, _session, socket) do
  post = Blog.get_post!(socket.assigns.current_scope, id)
  {:ok, assign(socket, :post, post)}
end

def handle_params(params, _uri, socket) do
  page = String.to_integer(params["page"] || "1")
  comments = Blog.list_comments(socket.assigns.post, page: page)
  {:noreply, stream(socket, :comments, comments, reset: true)}
end
```

## Navigation

| Use | Effect |
| --- | --- |
| `<.link href={...}>` | Full page load. |
| `<.link navigate={...}>` / `push_navigate/2` | Mounts a new LiveView in the same `live_session` and keeps the layout. |
| `<.link patch={...}>` / `push_patch/2` | Stays in the current LiveView, calls `handle_params/3`, sends a minimal diff and keeps scroll position. |

Put filter, sort and page state in the URL and use `patch`, so reloads and shared links reproduce the view.

## Streams

Streams keep large collections out of server memory: stream items are freed from socket state right after render.

```elixir
socket
|> stream(:songs, songs)                       # append (at: -1 is the default)
|> stream_insert(:songs, song, at: 0)          # prepend, or update in place if present
|> stream_delete(:songs, song)
|> stream(:songs, new_songs, reset: true)      # replace everything, e.g. after a filter
|> stream(:songs, songs, at: -1, limit: -10)   # keep only the last 10 on the client
```

```heex
<tbody id="songs" phx-update="stream">
  <tr :for={{dom_id, song} <- @streams.songs} id={dom_id}>
    <td>{song.title}</td>
  </tr>
</tbody>
```

- The immediate parent needs `phx-update="stream"` and a unique `id`. Each item needs the generated `dom_id`. Do not alter the generated ids.
- `stream_insert/4` does not inherit `:limit` from `stream/4`. Pass `limit:` on each insert.
- The limit is not enforced on the static render, so load only the number of items you want to show.
- Configure custom DOM ids with `stream_configure/3` before the first insert.
- `stream_insert(..., update_only: true)` updates an item without inserting it if it is missing.

## Async work

Async tasks start only once the socket is connected, so the static render stays fast.

```elixir
def mount(%{"slug" => slug}, _session, socket) do
  scope = socket.assigns.current_scope
  {:ok,
   socket
   |> assign_async(:org, fn -> {:ok, %{org: Orgs.fetch_org!(scope, slug)}} end)
   |> stream_async(:posts, fn -> {:ok, Blog.list_posts(scope), limit: 10} end)}
end
```

```heex
<.async_result :let={org} assign={@org}>
  <:loading>Loading organization...</:loading>
  <:failed :let={_failure}>There was an error loading the organization.</:failed>
  {org.name}
</.async_result>
```

- `assign_async/4` returns `{:ok, %{key => value}}` or `{:error, reason}`. Each key becomes a `Phoenix.LiveView.AsyncResult` with `loading`, `ok?`, `failed` and `result`. The `reset: true` option clears the previous result while reloading.
- `stream_async/4` (LiveView 1.1.5+) returns `{:ok, enumerable}` or `{:ok, enumerable, stream_opts}`. Stream options such as `reset: true` go in that return value. The `reset:` option on `stream_async/4` itself only resets the loading state.
- `start_async/4` plus `handle_async/3` gives you full control. The result arrives as `{:ok, value}` or `{:exit, reason}`. A later `start_async/4` with the same name wins, and `cancel_async/3` stops a task.
- Copy what the task needs out of `socket.assigns` first. Capturing `socket` copies the whole struct into the task process.
- Tasks are linked to the LiveView. A linked `Task.async/1` that crashes deep inside the work also takes the LiveView down. Rescue inside the task, or use `Task.Supervisor.async_nolink/3`.

## Function components

Prefer function components. The docs recommend reaching for `Phoenix.LiveComponent` only when you need its extra state.

```elixir
attr :size, :string, values: ~w(sm md lg), default: "md"
attr :rest, :global, include: ~w(form)
slot :inner_block, required: true

def button(assigns) do
  ~H"""
  <button class={"btn btn-#{@size}"} {@rest}>{render_slot(@inner_block)}</button>
  """
end
```

- `attr/3` and `slot/3` give compile-time warnings for missing required attrs, unknown attrs and literal values outside `:values`.
- Named slots can declare their own attrs (`slot :column do attr :label, :string end`). Pass values back to the caller with `render_slot(@col, item)` and `:let`.
- In LiveView 1.1+, add `:key` to comprehensions over items with stable ids (`<li :for={i <- @items} :key={i.id}>`) for better diffing. Without it, LiveView tracks changes by index.
- In LiveView 1.1+ with Phoenix 1.8+, colocated hooks (`<script :type={Phoenix.LiveView.ColocatedHook} name=".Name">`, referenced as `phx-hook=".Name"`) keep hook JavaScript next to the component. `<.portal>` renders content outside an `overflow: hidden` parent.

## Forms

```elixir
def mount(_params, _session, socket) do
  {:ok, assign(socket, :form, to_form(Accounts.change_user(%User{})))}
end

def handle_event("validate", %{"user" => params}, socket) do
  form = %User{} |> Accounts.change_user(params) |> to_form(action: :validate)
  {:noreply, assign(socket, :form, form)}
end

def handle_event("save", %{"user" => params}, socket) do
  case Accounts.create_user(socket.assigns.current_scope, params) do
    {:ok, _user} -> {:noreply, push_navigate(socket, to: ~p"/users")}
    {:error, changeset} -> {:noreply, assign(socket, :form, to_form(changeset))}
  end
end
```

```heex
<.form for={@form} id="user-form" phx-change="validate" phx-submit="save">
  <.input field={@form[:email]} phx-debounce="blur" />
  <button phx-disable-with="Saving...">Save</button>
</.form>
```

- Assign the form, not the changeset, and access fields as `@form[:field]`.
- Errors show only after the changeset has an action, which is why validate uses `to_form(action: :validate)`.
- LiveView 1.0 replaced `phx-feedback-for` with `used_input?/1`: show a field's errors only once it has been interacted with. The generated `core_components.ex` already does this.
- Give every `phx-change` form an `id` so LiveView can recover its values after a reconnect. LiveView 1.2 tests warn when it is missing.
- Use `<.inputs_for>` for nested associations and `phx-debounce` / `phx-throttle` to rate-limit events.

## JS commands

`Phoenix.LiveView.JS` runs on the client and is DOM-patch aware: its effects persist across server patches. Use it for UI-only changes such as toggling, showing a modal or adding classes, so they need no server round trip.

```heex
<button phx-click={JS.push("delete", value: %{id: @post.id}) |> JS.hide(to: "#post-#{@post.id}")}>
  Delete
</button>
<button phx-click={JS.toggle(to: "#menu")}>Menu</button>
```

- Common commands: `show`, `hide`, `toggle`, `add_class`, `remove_class`, `toggle_class`, `set_attribute`, `transition`, `dispatch`, `focus`, `push`, `navigate`, `patch`, `exec`.
- `JS.push/2` accepts `loading:` and `target:` options.
- In LiveView 1.2+, JS structs can also be sent to the client with `push_event/3`.

## PubSub

- Broadcast from the context after a successful write, not from the LiveView. Every caller (LiveView, controller, job) then notifies subscribers the same way.
- Subscribe only when connected. A subscription made during the static render belongs to a process that is about to exit.

```elixir
# context (shape of Phoenix 1.8 generated code)
def subscribe_posts(%Scope{} = scope),
  do: Phoenix.PubSub.subscribe(MyApp.PubSub, "user:#{scope.user.id}:posts")

# LiveView
def mount(_params, _session, socket) do
  if connected?(socket), do: Blog.subscribe_posts(socket.assigns.current_scope)
  {:ok, stream(socket, :posts, Blog.list_posts(socket.assigns.current_scope))}
end

def handle_info({type, %Post{}}, socket) when type in [:created, :updated, :deleted] do
  {:noreply, stream(socket, :posts, Blog.list_posts(socket.assigns.current_scope), reset: true)}
end
```

## Memory and change tracking

- Assign only what templates render. Every assign lives in the LiveView process for the life of the connection.
- For collections, prefer streams. `temporary_assigns` (returned from `mount/3` as `{:ok, socket, temporary_assigns: [...]}`) also reset after each render. Streams add insert, update, delete, reset and limit semantics on top.
- Don't load data inside templates. Don't define local variables in templates outside block constructs, because that disables change tracking.
- Pass explicit assigns to child components rather than all of `assigns`, so change tracking can skip unchanged children.
- Change assigns only with `assign/2,3`, `assign_new/3` and `update/3`. Changes made with `Map.put/3` won't re-render.

## Sources

- https://phoenix-live-view.hexdocs.pm/Phoenix.LiveView.html (mount, connected?/1, streams, async functions, linked processes)
- https://phoenix-live-view.hexdocs.pm/live-navigation.html
- https://phoenix-live-view.hexdocs.pm/Phoenix.Component.html (attr, slot, used_input?)
- https://phoenix-live-view.hexdocs.pm/form-bindings.html
- https://phoenix-live-view.hexdocs.pm/bindings.html (phx-debounce, phx-throttle)
- https://phoenix-live-view.hexdocs.pm/Phoenix.LiveView.JS.html
- https://phoenix-live-view.hexdocs.pm/assigns-eex.html (change tracking pitfalls)
- https://phoenix-live-view.hexdocs.pm/welcome.html (function vs live components)
- https://phoenix-live-view.hexdocs.pm/changelog.html (1.2 changes)
- https://github.com/phoenixframework/phoenix_live_view/blob/v1.1/CHANGELOG.md (stream_async in 1.1.5)
- https://github.com/phoenixframework/phoenix_live_view/blob/v1.0/CHANGELOG.md (used_input? replaces phx-feedback-for)
- https://www.phoenixframework.org/blog/phoenix-liveview-1-1-released
- https://github.com/phoenixframework/phoenix/blob/v1.8.15/priv/templates/phx.gen.live/index.ex.eex (connected? subscribe)
