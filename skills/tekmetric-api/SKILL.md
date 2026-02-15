---
name: tekmetric-api
description: Tekmetric REST API — authentication, paginated endpoints, sync patterns, and undocumented behaviors. Use when integrating with Tekmetric shop management data (customers, vehicles, repair orders, employees, appointments).
---

# Tekmetric API — Skill Reference

> **Full endpoint documentation**: `@meta-honman/docs/Tekmetric-API.txt`
> This skill focuses on patterns, gotchas, and integration knowledge that go beyond the raw docs.

---

## Environments

| Environment | Base URL                        | Rate Limit  |
| ----------- | ------------------------------- | ----------- |
| Sandbox     | `https://sandbox.tekmetric.com` | 300 req/min |
| Production  | `https://shop.tekmetric.com`    | 600 req/min |

All endpoints are under `/api/v1/`.

---

## Authentication

OAuth2 client credentials flow. Token does **not** expire until explicitly revoked.

```bash
curl -X POST 'https://sandbox.tekmetric.com/api/v1/oauth/token' \
  -H "Authorization: Basic $(echo -n 'CLIENT_ID:CLIENT_SECRET' | base64)" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials"
```

**Response:**

```json
{
  "access_token": "7de937e1-8574-4459-a0cc-bb4505e7803f",
  "token_type": "bearer",
  "scope": "1 2"
}
```

- `scope` is a **space-separated list of Shop IDs** the token has access to
- Use the token as: `-H "Authorization: Bearer <access_token>"`
- Token is long-lived — cache it and reuse until revoked

---

## Pagination

All list endpoints return a **Spring Data Page** envelope:

```json
{
  "content": [ ... ],
  "totalPages": 5,
  "totalElements": 450,
  "last": false,
  "first": true,
  "size": 100,
  "number": 0,
  "numberOfElements": 100
}
```

### Key Facts

| Field           | Meaning                                 |
| --------------- | --------------------------------------- |
| `content`       | Array of records for this page          |
| `number`        | Zero-indexed page number                |
| `size`          | Requested page size (capped at 100)     |
| `totalElements` | Total matching records across all pages |
| `totalPages`    | Total pages                             |
| `last`          | `true` if this is the final page        |
| `first`         | `true` if this is the first page        |

- **Max page size is 100** — any `size` param > 100 is silently capped
- `totalElements` is reliable for quick count-based verification
- Terminate paging when `last == true` OR `number + 1 >= totalPages`

---

## Core Endpoints

| Entity        | List                 | Single                    | Notes                         |
| ------------- | -------------------- | ------------------------- | ----------------------------- |
| Shops         | `GET /shops`         | `GET /shops/{id}`         | Not paginated — returns array |
| Customers     | `GET /customers`     | `GET /customers/{id}`     | Paginated                     |
| Vehicles      | `GET /vehicles`      | `GET /vehicles/{id}`      | Paginated                     |
| Repair Orders | `GET /repair-orders` | `GET /repair-orders/{id}` | Paginated, includes jobs      |
| Jobs          | `GET /jobs`          | `GET /jobs/{id}`          | Paginated                     |
| Employees     | `GET /employees`     | `GET /employees/{id}`     | Paginated                     |
| Appointments  | `GET /appointments`  | `GET /appointments/{id}`  | Paginated                     |

### Common Query Parameters

All paginated list endpoints accept:

| Param              | Type    | Description                          |
| ------------------ | ------- | ------------------------------------ |
| `shop`             | Integer | **Required** — filter by shop ID     |
| `size`             | Integer | Page size (max 100)                  |
| `page`             | Integer | Zero-indexed page number             |
| `updatedDateStart` | Date    | ISO 8601 — filter by updated date >= |
| `updatedDateEnd`   | Date    | ISO 8601 — filter by updated date <= |
| `deletedDateStart` | Date    | ISO 8601 — filter by deleted date >= |
| `deletedDateEnd`   | Date    | ISO 8601 — filter by deleted date <= |

---

## Date Formats

All dates use **ISO 8601 with Z suffix**: `2025-02-15T10:31:59Z`

Use `DateTime.to_iso8601/1` in Elixir — the default output with `Z` suffix is compatible.

---

## Error Handling

| HTTP Code | Meaning            | Action                         |
| --------- | ------------------ | ------------------------------ |
| 200       | Success            | —                              |
| 400       | Bad request        | Fix params                     |
| 401       | Invalid token      | Re-authenticate                |
| 403       | Insufficient scope | Token lacks shop access        |
| 404       | Not found          | —                              |
| 429       | Rate limited       | Backoff and retry              |
| 5xx       | Server error       | Retry with exponential backoff |

### Exponential Backoff for 429s

```
wait = min(2^n + random_ms, 60_000)  # n starts at 1
```

---

## Monetary Values

**All monetary fields are in cents** (integer). Examples:

- `laborSales: 13000` → $130.00
- `partsSales: 25997` → $259.97
- `cost: 15999` → $159.99

---

## Learnings (Undocumented Behaviors)

These are field-hardened findings from production integration work. They are **not** in the official Tekmetric documentation.

### 🔴 CRITICAL: Split Calls Required for Deleted Records

When querying `/repair-orders` (and likely other endpoints), combining regular date params with deleted date params causes the API to return **ONLY deleted records**:

```
# ❌ WRONG — returns ONLY deleted records, not both
GET /repair-orders?shop=1&updatedDateStart=...&deletedDateStart=...

# ✅ CORRECT — two separate calls, merge in app code
# Call 1: active/updated records
GET /repair-orders?shop=1&updatedDateStart=...&updatedDateEnd=...
# Call 2: deleted records
GET /repair-orders?shop=1&deletedDateStart=...&deletedDateEnd=...
```

Confirmed October 2025. This applies to Repair Orders, Customers, and Vehicles.

**Exception:** Appointments use `includeDeleted=true` parameter instead of separate calls.

### 🔴 CRITICAL: Employees Endpoint Does NOT Return `shopId`

The `/employees` endpoint accepts a `shop` query parameter for filtering, but the response body **does not include** a `shopId` field. This means:

- You must associate `shop_id` from the **request context**, not the response
- If you rely on `shopId` being in the response for database mapping, it will always be `nil`
- This caused a bug where `has_any_employees?` checks always returned `false`, triggering full re-syncs every cycle

### 🟡 Page Size Silently Capped

Requesting `size=500` does **not** return an error — it silently returns 100 results. Always use `size=100` explicitly to make code behavior match expectations.

### 🟡 Jobs Endpoint Filters by Job Update Date

The standalone `/jobs` endpoint filters by `job.updatedDate`, which may **miss** jobs that were part of a Repair Order update but not individually updated. For reliable job syncing, extract jobs from the embedded `jobs` array in `/repair-orders/{id}` responses instead.

### 🟡 Query Parameter Format

The API accepts both formats for query parameters:

```elixir
# Both work — Req library handles either
{"shop", shop_id}         # string-keyed tuple
[shop: shop_id]           # atom-keyed keyword list
```

Standardize on **string-keyed tuples** for consistency across modules.

### 🟡 Token Scope

The `scope` field in the token response is a space-separated string of Shop IDs, **not** a permission scope. Example: `"scope": "1 2"` means access to shops 1 and 2.

### 🟢 Observed Latency

Network latency (~250-400ms per request) is typically the bottleneck before hitting rate limits. Sequential throughput maxes out around 200-240 req/min on the sandbox, well below the 300 req/min rate limit.

---

## Elixir / Req Integration Pattern

### Provider-Aware Client

```elixir
defmodule SyncPlugins.Tekmetric.Client do
  @doc "GET request using the provider's base_url and credentials."
  def get(%SmsProvider{} = provider, path, params \\ []) do
    Req.get(
      url: provider.base_url <> "/api/v1" <> path,
      headers: [{"Authorization", "Bearer #{get_token(provider)}"}],
      params: params
    )
  end
end
```

### Paginated Fetch

```elixir
defmodule SyncPlugins.Tekmetric.Paging do
  @doc "Fetch all pages using a closure that binds the provider."
  def list_all_pages(get_fn, path, params, opts \\ []) do
    size = Keyword.get(opts, :size, 100)
    do_fetch(get_fn, path, [{"size", size} | params], 0, [])
  end

  defp do_fetch(get_fn, path, params, page, acc) do
    case get_fn.(path, [{"page", page} | params]) do
      {:ok, %{body: %{"content" => content, "last" => true}}} ->
        {:ok, acc ++ content}
      {:ok, %{body: %{"content" => content}}} ->
        do_fetch(get_fn, path, params, page + 1, acc ++ content)
      {:error, _} = error ->
        error
    end
  end
end
```

### Typical Module Pattern

```elixir
defmodule SyncPlugins.Tekmetric.Customers do
  def list_customers(%SmsProvider{} = provider, shop_id, params \\ []) do
    get_fn = fn path, p -> Client.get(provider, path, p) end
    Paging.list_all_pages(get_fn, "/customers", [{"shop", shop_id} | params])
  end

  def sync_recent(%SmsProvider{} = provider, tenant_id, shop_id, %DateTime{} = since) do
    updated = list_customers(provider, shop_id, [
      {"updatedDateStart", DateTime.to_iso8601(since)}
    ])

    deleted = list_customers(provider, shop_id, [
      {"deletedDateStart", DateTime.to_iso8601(since)}
    ])

    # Merge by ID — deleted records may overlap with updated
    merged = Map.merge(
      Map.new(updated, &{&1["id"], &1}),
      Map.new(deleted, &{&1["id"], &1})
    ) |> Map.values()

    upsert_many(provider, tenant_id, merged)
  end
end
```

---

## Sync Strategy Summary

| Entity        | Updated Records                                | Deleted Records                  | Merge? |
| ------------- | ---------------------------------------------- | -------------------------------- | ------ |
| Customers     | `updatedDateStart/End`                         | `deletedDateStart/End`           | Yes    |
| Vehicles      | `updatedDateStart/End`                         | `deletedDateStart/End`           | Yes    |
| Repair Orders | `updatedDateStart/End`                         | `deletedDateStart/End`           | Yes    |
| Jobs          | Derived from RO `/repair-orders/{id}`          | Mark missing as deleted          | N/A    |
| Employees     | `updatedDateStart/End`                         | Full re-fetch (no delete filter) | No     |
| Appointments  | `updatedDateStart/End` + `includeDeleted=true` | Same call                        | No     |
| Shops         | Full list (small dataset)                      | N/A                              | No     |
