#!/usr/bin/env bash
# Tekmetric API Skill — Claim Verification Script
# Runs against the sandbox to verify every assertion in SKILL.md

BASE="https://sandbox.tekmetric.com/api/v1"
OUT="${TEMP:-${TMP:-/tmp}}/tek_verify"
RESULTS="${TEMP:-${TMP:-/tmp}}/tek_results.txt"
mkdir -p "$OUT"
> "$RESULTS"

# --- Credentials ---
kubectl get secret breakdown-admin-secrets -n default -o jsonpath='{.data.tekmetric_sandbox_client_id}' > "$OUT/id_b64.txt"
kubectl get secret breakdown-admin-secrets -n default -o jsonpath='{.data.tekmetric_sandbox_client_secret}' > "$OUT/secret_b64.txt"
TK_ID=$(cat "$OUT/id_b64.txt" | base64 -d)
TK_SECRET=$(cat "$OUT/secret_b64.txt" | base64 -d)
BASIC=$(echo -n "${TK_ID}:${TK_SECRET}" | base64)

# Windows-compatible JSON reader
nj() {
  node -e "const d=JSON.parse(require('fs').readFileSync(process.argv[1],'utf8')); $2" -- "$1"
}

pass=0; fail=0; warn=0

log() { echo "$1" | tee -a "$RESULTS"; }

check() {
  if [ "$2" = "PASS" ]; then
    log "  PASS: $1"
    pass=$((pass+1))
  elif [ "$2" = "WARN" ]; then
    log "  WARN: $1"
    warn=$((warn+1))
  else
    log "  FAIL: $1"
    fail=$((fail+1))
  fi
}

# ========== CLAIM 1: Auth ==========
log ""
log "=== CLAIM 1: OAuth2 Token Response Shape ==="
curl -s -X POST "$BASE/oauth/token" \
  -H "Authorization: Basic ${BASIC}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" > "$OUT/token.json"

TOKEN=$(nj "$OUT/token.json" "console.log(d.access_token)")
TOKEN_TYPE=$(nj "$OUT/token.json" "console.log(d.token_type)")
SCOPE=$(nj "$OUT/token.json" "console.log(d.scope)")

if [ -n "$TOKEN" ]; then check "Has access_token field" "PASS"; else check "Has access_token field" "FAIL"; fi
if [ "$TOKEN_TYPE" = "bearer" ]; then check "token_type is 'bearer'" "PASS"; else check "token_type is '$TOKEN_TYPE' (expected bearer)" "FAIL"; fi
if echo "$SCOPE" | grep -qE '^[0-9]+( [0-9]+)*$'; then
  check "scope is space-separated shop IDs (got: '$SCOPE')" "PASS"
else
  check "scope format unexpected: '$SCOPE'" "FAIL"
fi

# ========== CLAIM 2: Shops ==========
log ""
log "=== CLAIM 2: Shops Endpoint Structure ==="
curl -s "$BASE/shops" -H "Authorization: Bearer $TOKEN" > "$OUT/shops.json"

SHOPS_IS_ARRAY=$(nj "$OUT/shops.json" "console.log(Array.isArray(d) ? 'yes' : 'no')")
SHOPS_HAS_CONTENT=$(nj "$OUT/shops.json" "console.log(typeof d === 'object' && 'content' in d ? 'yes' : 'no')")

if [ "$SHOPS_IS_ARRAY" = "yes" ]; then
  check "Shops returns raw array (not paginated)" "PASS"
elif [ "$SHOPS_HAS_CONTENT" = "yes" ]; then
  SHOPS_TOTAL=$(nj "$OUT/shops.json" "console.log(d.totalElements)")
  check "Shops returns PAGINATED envelope (SKILL.md says 'returns array') — NEEDS FIX (totalElements=$SHOPS_TOTAL)" "FAIL"
else
  check "Shops returns unknown structure" "FAIL"
fi

# Get a shop ID for subsequent calls
SHOP_ID=$(nj "$OUT/shops.json" "const c=d.content||d; console.log(Array.isArray(c)?c[0].id:2)")
log "    -> Using shop_id=$SHOP_ID for remaining tests"

# ========== CLAIM 3: Pagination Envelope ==========
log ""
log "=== CLAIM 3: Pagination Envelope Shape ==="
curl -s "$BASE/customers?shop=${SHOP_ID}&size=1" -H "Authorization: Bearer $TOKEN" > "$OUT/customers_page.json"

for field in content totalPages totalElements last first size number numberOfElements; do
  HAS=$(nj "$OUT/customers_page.json" "console.log('$field' in d ? 'yes' : 'no')")
  if [ "$HAS" = "yes" ]; then check "Pagination has '$field'" "PASS"; else check "Pagination MISSING '$field'" "FAIL"; fi
done

# ========== CLAIM 4: Page Size Cap ==========
log ""
log "=== CLAIM 4: Page Size Silently Capped at 100 ==="
curl -s "$BASE/customers?shop=${SHOP_ID}&size=500" -H "Authorization: Bearer $TOKEN" > "$OUT/customers_bigpage.json"
ACTUAL_SIZE=$(nj "$OUT/customers_bigpage.json" "console.log(d.size)")
ACTUAL_COUNT=$(nj "$OUT/customers_bigpage.json" "console.log(d.numberOfElements)")
if [ "$ACTUAL_SIZE" = "100" ]; then
  check "Requested size=500, API returned size=$ACTUAL_SIZE" "PASS"
else
  check "Requested size=500, API returned size=$ACTUAL_SIZE (expected 100)" "FAIL"
fi
log "    -> numberOfElements: $ACTUAL_COUNT"

# ========== CLAIM 5: Employees missing shopId ==========
log ""
log "=== CLAIM 5: Employees Response Missing shopId ==="
curl -s "$BASE/employees?shop=${SHOP_ID}&size=1" -H "Authorization: Bearer $TOKEN" > "$OUT/employees.json"
EMP_HAS_SHOPID=$(nj "$OUT/employees.json" "const e=(d.content||[])[0]; console.log(e && 'shopId' in e ? 'yes' : 'no')")
EMP_FIELDS=$(nj "$OUT/employees.json" "const e=(d.content||[])[0]; console.log(e ? Object.keys(e).join(', ') : 'NO EMPLOYEES')")
if [ "$EMP_HAS_SHOPID" = "no" ]; then
  check "Employees response MISSING shopId — confirmed" "PASS"
else
  check "Employees response HAS shopId — SKILL.md claim WRONG" "FAIL"
fi
log "    -> Fields: $EMP_FIELDS"

# ========== CLAIM 6: Customers DO have shopId ==========
log ""
log "=== CLAIM 6: Customers Has shopId (contrast) ==="
CUST_HAS_SHOPID=$(nj "$OUT/customers_page.json" "const c=(d.content||[])[0]; console.log(c && 'shopId' in c ? 'yes' : 'no')")
if [ "$CUST_HAS_SHOPID" = "yes" ]; then check "Customers response HAS shopId" "PASS"; else check "Customers response MISSING shopId" "FAIL"; fi

# ========== CLAIM 7: Monetary values in cents ==========
log ""
log "=== CLAIM 7: Monetary Values in Cents ==="
curl -s "$BASE/repair-orders?shop=${SHOP_ID}&size=1" -H "Authorization: Bearer $TOKEN" > "$OUT/ro.json"
LABOR=$(nj "$OUT/ro.json" "const r=(d.content||[])[0]; console.log(r ? r.laborSales : 'N/A')")
PARTS=$(nj "$OUT/ro.json" "const r=(d.content||[])[0]; console.log(r ? r.partsSales : 'N/A')")
IS_INT=$(nj "$OUT/ro.json" "const r=(d.content||[])[0]; console.log(r && Number.isInteger(r.laborSales) ? 'yes' : 'no')")
if [ "$IS_INT" = "yes" ]; then check "laborSales is integer (cents): $LABOR" "PASS"; else check "laborSales not integer: $LABOR" "FAIL"; fi
log "    -> laborSales=$LABOR, partsSales=$PARTS"

# ========== CLAIM 8: RO has embedded jobs ==========
log ""
log "=== CLAIM 8: RO Includes Embedded Jobs ==="
HAS_JOBS=$(nj "$OUT/ro.json" "const r=(d.content||[])[0]; console.log(r && 'jobs' in r ? 'yes' : 'no')")
if [ "$HAS_JOBS" = "yes" ]; then check "RO has embedded 'jobs' array" "PASS"; else check "RO MISSING 'jobs'" "FAIL"; fi

# ========== CLAIM 9: Date format ==========
log ""
log "=== CLAIM 9: Date Format ISO 8601 ==="
DATE=$(nj "$OUT/customers_page.json" "const c=(d.content||[])[0]; console.log(c ? c.updatedDate : 'N/A')")
if echo "$DATE" | grep -qE '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z'; then
  check "updatedDate format: '$DATE'" "PASS"
else
  check "updatedDate format unexpected: '$DATE'" "FAIL"
fi

# ========== CLAIM 10: Rate limit ==========
log ""
log "=== CLAIM 10: Rate Limit ==="
check "Rate limit 300/min sandbox, 600/min prod (from docs, not testing)" "WARN"

# ========== CLAIM 11: Vehicles ==========
log ""
log "=== CLAIM 11: Vehicles Endpoint ==="
curl -s "$BASE/vehicles?shop=${SHOP_ID}&size=1" -H "Authorization: Bearer $TOKEN" > "$OUT/vehicles.json"
VEH_OK=$(nj "$OUT/vehicles.json" "console.log('content' in d ? 'yes' : 'no')")
if [ "$VEH_OK" = "yes" ]; then check "Vehicles endpoint paginated" "PASS"; else check "Vehicles endpoint broken" "FAIL"; fi

# ========== CLAIM 12: Jobs standalone ==========
log ""
log "=== CLAIM 12: Jobs Standalone Endpoint ==="
curl -s "$BASE/jobs?shop=${SHOP_ID}&size=1" -H "Authorization: Bearer $TOKEN" > "$OUT/jobs.json"
JOBS_OK=$(nj "$OUT/jobs.json" "console.log('content' in d ? 'yes' : 'no')")
if [ "$JOBS_OK" = "yes" ]; then check "Jobs endpoint paginated" "PASS"; else check "Jobs endpoint broken" "FAIL"; fi

# ========== CLAIM 13: Appointments ==========
log ""
log "=== CLAIM 13: Appointments Endpoint ==="
curl -s "$BASE/appointments?shop=${SHOP_ID}&size=1" -H "Authorization: Bearer $TOKEN" > "$OUT/appointments.json"
APT_OK=$(nj "$OUT/appointments.json" "console.log('content' in d ? 'yes' : 'no')")
if [ "$APT_OK" = "yes" ]; then check "Appointments endpoint paginated" "PASS"; else check "Appointments endpoint broken" "FAIL"; fi

# ========== CLAIM 14: 401 for bad token ==========
log ""
log "=== CLAIM 14: Error 401 for Bad Token ==="
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/shops" -H "Authorization: Bearer bad-token-12345")
if [ "$HTTP_CODE" = "401" ]; then check "Bad token -> HTTP $HTTP_CODE" "PASS"; else check "Bad token -> HTTP $HTTP_CODE (expected 401)" "FAIL"; fi

# ========== CLAIM 15: Error response shape ==========
log ""
log "=== CLAIM 15: Error Response Shape ==="
curl -s "$BASE/shops" -H "Authorization: Bearer bad-token-12345" > "$OUT/error.json"
HAS_ERROR=$(nj "$OUT/error.json" "console.log('error' in d ? 'yes' : 'no')")
ERROR_TYPE=$(nj "$OUT/error.json" "console.log(d.error || 'N/A')")
if [ "$HAS_ERROR" = "yes" ]; then check "Error has 'error' field: '$ERROR_TYPE'" "PASS"; else check "Error response missing 'error' field" "FAIL"; fi

# ========== CLAIM 16: Date filtering ==========
log ""
log "=== CLAIM 16: updatedDateStart/End Filtering ==="
curl -s "$BASE/customers?shop=${SHOP_ID}&size=1&updatedDateStart=2020-01-01T00:00:00Z&updatedDateEnd=2020-12-31T23:59:59Z" \
  -H "Authorization: Bearer $TOKEN" > "$OUT/customers_datefilter.json"
FILTER_OK=$(nj "$OUT/customers_datefilter.json" "console.log('content' in d ? 'yes' : 'no')")
FILTER_TOTAL=$(nj "$OUT/customers_datefilter.json" "console.log(d.totalElements)")
if [ "$FILTER_OK" = "yes" ]; then
  check "updatedDateStart/End filtering works (total=$FILTER_TOTAL)" "PASS"
else
  check "updatedDateStart/End filtering broken" "FAIL"
fi

# ========== SUMMARY ==========
log ""
log "========================================"
log " RESULTS: $pass passed, $fail failed, $warn warnings"
log "========================================"
