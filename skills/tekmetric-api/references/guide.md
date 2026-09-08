# Tekmetric API — Skill Reference

> **Bundled endpoint documentation**: See [Tekmetric-API.txt](Tekmetric-API.txt).
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

OAuth2 client credentials flow. The bundled historical sandbox observations found long-lived tokens; honor any `expires_in` value returned by the current server.

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
- Cache the token according to current expiry metadata and handle authentication failures.

### Historical token observations (2026-02-15; not a current guarantee)

- Repeated sandbox requests returned the same token UUID during that observation. Do not rely on token endpoint calls to rotate a compromised token.
- The observed tokens were long-lived; this did not establish a permanent non-expiry contract.
- No self-service rotation was documented in that test; verify the provider’s current revocation process.
- Honor `expires_in` when present. Its absence is not proof that a token can never expire; handle 401 with one controlled refresh and fail clearly if access remains denied.

**Credential handling:** Protect both the access token and client credentials. Use the project’s configured secret manager and runtime injection; do not log them or add plaintext to tracked files or shell profiles. Cache tokens according to the application’s lifecycle and the actual server response. Confirm current revocation options with Tekmetric if a credential is compromised.

---

## Pagination

Paginated list endpoints return a **Spring Data Page** envelope; `/shops` instead returns an array:

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
delay_ms = min(1000 * (2 ** attempt) + jitter_ms, 60_000)  # attempt starts at 0; bound attempts and total elapsed time
```

---

## Monetary Values

**All monetary fields are in cents** (integer). Examples:

- `laborSales: 13000` → $130.00
- `partsSales: 25997` → $259.97
- `cost: 15999` → $159.99

---

## Development Rules

### Verify endpoint assumptions

For a new or uncertain endpoint behavior, prefer a minimal read-only sandbox request when authorized credentials and access are available. Otherwise use recorded fixtures and current documentation, and report that live behavior is unverified. Do not block independent implementation or reach into production merely to satisfy a checklist.

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

### Pagination and merging

Helpers should return `{:ok, records}` or `{:error, reason}` consistently. Check HTTP status before matching a page shape. Validate `content`, `last`, and page metadata; bound page count and detect no progress. Do not treat an error response as a successful empty page. Accumulate pages without repeated quadratic list concatenation.

```elixir
with {:ok, updated} <- list_customers(provider, shop_id, updated_params),
     {:ok, deleted} <- list_customers(provider, shop_id, deleted_params) do
  merged = Map.merge(Map.new(updated, &{&1["id"], &1}),
                     Map.new(deleted, &{&1["id"], &1}))
  upsert_many(provider, tenant_id, Map.values(merged))
end
```

This is a caller pattern, not a standalone client. Bind provider, tenant, and shop explicitly. Deleted results take precedence on overlap. Advance the sync checkpoint only after both fetches and persistence succeed. Only infer deletion from absence after a successful complete authoritative snapshot, never a partial or failed page.

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

Use the target application's configured sandbox secret source and explicitly identified shop. Do not assume a particular Kubernetes secret, namespace, tenant, or cloud project exists in every repository. Never persist credentials in a shell profile or print raw customer data for a routine test. Parse token responses with a JSON parser and check HTTP failures before consuming fields.

The original authors recorded sandbox observations on February 15, 2026; this review did not rerun those live requests. Treat undocumented behavior, latency, and quotas as dated observations to verify for the target account. Consult the bundled endpoint reference and current provider documentation before changing integrations.
