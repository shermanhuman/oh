# Architecture and testing

Verified against Phoenix 1.8.x and LiveView 1.2.x docs and the Phoenix 1.8.15 generator templates.

## Contents

- [Contexts](#contexts)
- [Scopes (Phoenix 1.8+)](#scopes-phoenix-18)
- [Generators and layouts](#generators-and-layouts)
- [Test cases and the SQL sandbox](#test-cases-and-the-sql-sandbox)
- [Testing contexts](#testing-contexts)
- [Testing LiveViews](#testing-liveviews)
- [Sources](#sources)

## Contexts

- A context is a plain module that encapsulates data access and validation for one area of the app. It usually talks to the database through Ecto, or to an external API.
- The web layer (controllers, LiveViews, components) calls context functions. It does not build queries or call `Repo`. That keeps business rules in one place, reusable from jobs, scripts and other contexts.
- Name contexts for their purpose (`Accounts`, `Catalog`, `Orders`), not after a single table. Colocate related schemas: `mix phx.gen.live Posts Comment comments post_id:references:posts body:text` puts comments inside the `Posts` context.
- Contexts return plain data and `{:ok, _}` / `{:error, changeset}` tuples. Don't return HTML, conn or socket.
- Across contexts, call the other context's public functions rather than reaching into its schemas or `Repo` queries.

## Scopes (Phoenix 1.8+)

A scope is a struct holding request information such as the current user, organization and permissions. `mix phx.gen.auth` generates `MyApp.Accounts.Scope` and assigns it as `:current_scope`, through the `fetch_current_scope_for_user` plug for HTTP and the `mount_current_scope` on_mount hook for LiveView.

Generated context functions take the scope first and filter by it. That makes data access scoped by default:

```elixir
def list_posts(%Scope{} = scope) do
  Repo.all_by(Post, user_id: scope.user.id)
end

def get_post!(%Scope{} = scope, id) do
  Repo.get_by!(Post, id: id, user_id: scope.user.id)
end

def update_post(%Scope{} = scope, %Post{} = post, attrs) do
  true = post.user_id == scope.user.id

  with {:ok, post = %Post{}} <- post |> Post.changeset(attrs, scope) |> Repo.update() do
    broadcast_post(scope, {:updated, post})
    {:ok, post}
  end
end
```

- LiveViews pass `socket.assigns.current_scope` to every context call. Controllers pass `conn.assigns.current_scope`.
- PubSub topics include the scope key (for example `"user:#{scope.user.id}:posts"`), so subscribers receive only their own data.
- Generators read scopes from `config :my_app, :scopes`, which sets the module, `assign_key`, `access_path`, `schema_key` and test helpers. Add fields such as an organization to the scope struct when access depends on them.

## Generators and layouts

- `mix phx.gen.live`, `phx.gen.html`, `phx.gen.json` and `phx.gen.context` produce a context, a schema, a migration and tests. Use them as a reference for current idioms even when you write code by hand.
- Phoenix 1.8 `mix phx.gen.auth` includes magic-link login and "sudo mode".
- Phoenix 1.8 has a single `root.html.heex`. App layouts are function components called from templates (`<Layouts.app flash={@flash} current_scope={@current_scope}>`) and can take attrs and slots.
- New 1.8 apps include an `AGENTS.md` with framework usage guidelines for coding agents.

## Test cases and the SQL sandbox

- `MyApp.DataCase` is for context and schema tests. `MyAppWeb.ConnCase` is for controller and LiveView tests and builds a `conn`. Both call `DataCase.setup_sandbox/1`:

```elixir
def setup_sandbox(tags) do
  pid = Ecto.Adapters.SQL.Sandbox.start_owner!(MyApp.Repo, shared: not tags[:async])
  on_exit(fn -> Ecto.Adapters.SQL.Sandbox.stop_owner(pid) end)
end
```

- Each test runs in a transaction that is rolled back afterwards, so tests don't see each other's data.
- `use MyApp.DataCase, async: true` runs the module concurrently with other async modules. Tests inside one module still run serially.
- In async mode, any extra process that queries the database needs `Ecto.Adapters.SQL.Sandbox.allow/3`. Otherwise you get `DBConnection.OwnershipError`. Shared mode (a non-async test) avoids allowances but cannot run concurrently.
- An "owner exited" error means a process was still using the connection when the test ended. Wait for that work before the test exits.

## Testing contexts

Test the public API of the context with fixtures. Assert on the return tuples and use `errors_on/1` for changeset errors.

```elixir
use MyApp.DataCase, async: true

test "create_post/2 with invalid data returns an error changeset" do
  scope = user_scope_fixture()
  assert {:error, changeset} = Blog.create_post(scope, %{title: nil})
  assert %{title: ["can't be blank"]} = errors_on(changeset)
end
```

## Testing LiveViews

```elixir
use MyAppWeb.ConnCase, async: true
import Phoenix.LiveViewTest

setup :register_and_log_in_user

test "creates a post", %{conn: conn} do
  {:ok, view, html} = live(conn, ~p"/posts")
  assert html =~ "Listing Posts"

  assert view |> form("#post-form", post: %{title: ""}) |> render_change() =~ "can&#39;t be blank"

  {:ok, _view, html} =
    view
    |> form("#post-form", post: %{title: "Hello"})
    |> render_submit()
    |> follow_redirect(conn, ~p"/posts")

  assert html =~ "Hello"
end
```

- `live/2` performs the static render and then connects. It returns `{:ok, view, html}`, or `{:error, {:redirect, _}}` when mount redirects.
- Drive events through elements: `element(view, "button", "Delete") |> render_click()`, `form/3` with `render_change/2` and `render_submit/2`. The docs prefer this style because it checks that the event actually exists in the rendered HTML.
- Assert with `has_element?(view, "#post-#{id}")` or `has_element?(view, selector, text_filter)` rather than matching large HTML strings.
- Use `assert_patch/2`, `assert_redirect/2` and `follow_redirect/3` for navigation, and `render_async/2` to wait for `assign_async`, `stream_async` and `start_async` work. `open_browser/1` helps when debugging.
- Test function components with `render_component/2` or the `~H` sigil plus `rendered_to_string/1`.
- LiveView 1.1 moved `Phoenix.LiveViewTest` from Floki to LazyHTML. Selectors like `:has()` and `:is()` work, and the Floki-only `fl-contains` is replaced by the `text_filter` argument.
- LiveView 1.2 checks rendered HTML in tests. By default a duplicate DOM id or duplicate LiveComponent raises, and a `phx-change` form without an `id` warns (opt out with `phx-ignore-missing-id` or `phx-auto-recover="ignore"`). Change this with `config :phoenix_live_view, :test_warnings` (keys `:duplicate_id`, `:duplicate_live_component`, `:missing_form_id`; values `:raise`, `:warn`, `:ignore`), or per test with the `on_error:` option of `live/3`.

## Sources

- https://phoenix.hexdocs.pm/contexts.html
- https://phoenix.hexdocs.pm/scopes.html
- https://phoenix.hexdocs.pm/testing.html (ConnCase, async)
- https://phoenix.hexdocs.pm/testing_contexts.html (DataCase, setup_sandbox)
- https://phoenix.hexdocs.pm/changelog.html (1.8: scopes, magic links, single root layout, Repo.transact)
- https://www.phoenixframework.org/blog/phoenix-1-8-released
- https://ecto-sql.hexdocs.pm/Ecto.Adapters.SQL.Sandbox.html
- https://phoenix-live-view.hexdocs.pm/changelog.html (1.2 test warnings)
- https://phoenix-live-view.hexdocs.pm/Phoenix.LiveViewTest.html (`on_error`, `:test_warnings`)
- https://www.phoenixframework.org/blog/phoenix-liveview-1-1-released (LazyHTML)
- https://github.com/phoenixframework/phoenix/tree/v1.8.15/priv/templates (phx.gen.context, phx.gen.live, live_test templates)
