---
name: tekmetric-api
description: Tekmetric REST API — authentication, paginated endpoints, sync patterns, and undocumented behaviors. Use when integrating with Tekmetric shop management data (customers, vehicles, repair orders, employees, appointments).
---

# Tekmetric API — Skill Reference

> **Full endpoint documentation**: See `Tekmetric-API.txt` in this skill directory.
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

### Error Response Formats (3 different shapes!)

The API uses **three different** error response formats depending on the endpoint and error type:

**1. OAuth token errors** (POST `/oauth/token`):

```json
{"error": "invalid_client"}
// or
{"error": "unsupported_grant_type", "error_description": "OAuth 2.0 Parameter: grant_type"}
```

**2. Bearer token 401** (invalid/expired token on API endpoints):

```
HTTP 401 — empty body (no JSON)
```

**3. API-level errors** (403 forbidden, etc.):

```json
{ "type": "ERROR", "message": "Access Denied", "data": null, "details": {} }
```

⚠️ Always check the HTTP status code first — don't assume a JSON body exists.

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

## Development Rules

### 🔴 ALWAYS curl-test before committing code

**Before writing or modifying any code that interacts with the Tekmetric API, verify the actual API behavior with a direct curl call first.** Do not trust the official documentation alone — it is incomplete and sometimes inaccurate.

This rule applies when:

- **Integrating a new endpoint** — curl it, inspect the full response shape, note which fields are present/absent
- **Using a new query parameter** — curl with and without it to confirm the actual filtering behavior
- **Combining parameters** — the API has known cases where parameter combinations produce surprising results (e.g., mixing `updatedDateStart` with `deletedDateStart`)
- **Debugging unexpected sync behavior** — curl the raw API to isolate whether the issue is API-side or code-side

This rule does NOT apply to:

- Refactoring code that handles a response shape you've already verified
- Changes to local-only logic (database upserts, worker scheduling, etc.)

**Why this matters:** This API has undocumented behaviors that have caused production bugs. The employees endpoint silently omits `shopId`, error responses come in 3 different formats, and page sizes are silently capped. Every one of these was discovered through direct curl testing, not from reading docs.

See the [Local Development & Testing](#local-development--testing) section for ready-to-use curl and PowerShell examples.

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

---

## Local Development & Testing

### Retrieving Sandbox Credentials

Sandbox credentials are stored as Kubernetes secrets in the `breakdown-admin-secrets` secret (namespace: `default`).

**Git Bash:**

```bash
# Extract credentials
TK_ID=$(kubectl get secret breakdown-admin-secrets -n default \
  -o jsonpath='{.data.tekmetric_sandbox_client_id}' | base64 -d)
TK_SECRET=$(kubectl get secret breakdown-admin-secrets -n default \
  -o jsonpath='{.data.tekmetric_sandbox_client_secret}' | base64 -d)

# Set for local use (optional — add to shell profile for persistence)
export TEKMETRIC_SANDBOX_CLIENT_ID="$TK_ID"
export TEKMETRIC_SANDBOX_CLIENT_SECRET="$TK_SECRET"
```

**PowerShell:**

```powershell
# Extract credentials
$TK_ID = kubectl get secret breakdown-admin-secrets -n default `
  -o jsonpath='{.data.tekmetric_sandbox_client_id}' | ForEach-Object {
    [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($_))
  }
$TK_SECRET = kubectl get secret breakdown-admin-secrets -n default `
  -o jsonpath='{.data.tekmetric_sandbox_client_secret}' | ForEach-Object {
    [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($_))
  }

# Set for local use
$env:TEKMETRIC_SANDBOX_CLIENT_ID = $TK_ID
$env:TEKMETRIC_SANDBOX_CLIENT_SECRET = $TK_SECRET
```

### Testing API Calls

**Git Bash (curl):**

```bash
# 1. Get a token
BASIC=$(echo -n "${TK_ID}:${TK_SECRET}" | base64)
TOKEN=$(curl -s -X POST 'https://sandbox.tekmetric.com/api/v1/oauth/token' \
  -H "Authorization: Basic ${BASIC}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

# 2. List shops
curl -s 'https://sandbox.tekmetric.com/api/v1/shops' \
  -H "Authorization: Bearer $TOKEN"

# 3. Fetch customers (paginated)
curl -s 'https://sandbox.tekmetric.com/api/v1/customers?shop=2&size=5' \
  -H "Authorization: Bearer $TOKEN"

# 4. Fetch a single repair order with embedded jobs
curl -s 'https://sandbox.tekmetric.com/api/v1/repair-orders?shop=2&size=1' \
  -H "Authorization: Bearer $TOKEN"
```

**PowerShell (Invoke-RestMethod):**

```powershell
# 1. Get a token
$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${TK_ID}:${TK_SECRET}"))
$tokenResp = Invoke-RestMethod -Method Post `
  -Uri 'https://sandbox.tekmetric.com/api/v1/oauth/token' `
  -Headers @{ Authorization = "Basic $basic"; 'Content-Type' = 'application/x-www-form-urlencoded' } `
  -Body 'grant_type=client_credentials'
$token = $tokenResp.access_token

# 2. List shops
Invoke-RestMethod -Uri 'https://sandbox.tekmetric.com/api/v1/shops' `
  -Headers @{ Authorization = "Bearer $token" }

# 3. Fetch customers (paginated)
Invoke-RestMethod -Uri 'https://sandbox.tekmetric.com/api/v1/customers?shop=2&size=5' `
  -Headers @{ Authorization = "Bearer $token" }
```

All assertions in this document were verified against the live sandbox API on **2026-02-15** — 23 passed, 0 failed, 1 warning (rate limit not tested).
