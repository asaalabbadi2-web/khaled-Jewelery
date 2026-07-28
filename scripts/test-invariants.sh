#!/usr/bin/env bash
# test-invariants.sh — backend invariant smoke suite (local staging only)
#
# Tests:
#   INV-4 (A) online reservation blocks POS claim   → Commerce API 409 ITEM_ALREADY_RESERVED
#   INV-4 (B) POS claim blocks online reservation   → Commerce API 409 ITEM_POS_CLAIMED
#   ATOMICITY  concurrent POS claims on one item     → exactly one 201, one 409
#   N4-IDEM    ERP internal sync idempotency guard   → second call returns 200 already_processed
#
# Prerequisites: make up (or make reset) must have completed successfully.
# State note: script is self-cleaning (releases claims after each test).
# If a test fails mid-run, run `make reset` before re-running.
#
# Usage:
#   bash scripts/test-invariants.sh
#
# ─── Config — edit these to match your .env.local / docker-compose.local.yml ─
COMMERCE="http://localhost:8000"
ERP_DEBUG="http://localhost:8001"   # requires `make up-debug`
POS_SECRET="local-pos-secret-dev"
INTERNAL_SECRET="local-internal-secret-dev"
JWT_SECRET="local-jwt-secret-dev"
COMPOSE_FILE="docker-compose.local.yml"

# Items used per test (must exist in seed/commerce_seed.sql):
ITEM_A=101   # INV-4 direction A (reservation blocks POS claim)
ITEM_B=102   # INV-4 direction B (POS claim blocks reservation)
ITEM_C=201   # atomicity test (two concurrent POS claims)
ITEM_D=301   # N4 idempotency test (ERP internal sync)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PASS=0
FAIL=0

_green() { printf '\e[32m%s\e[0m\n' "$*"; }
_red()   { printf '\e[31m%s\e[0m\n' "$*"; }

pass() { PASS=$((PASS+1)); _green "  PASS  $1"; }
fail() { FAIL=$((FAIL+1)); _red   "  FAIL  $1 — $2"; }

# Assert HTTP status code; prints body on failure
assert_status() {
    local label="$1" expected="$2" actual="$3" body="$4"
    if [ "$actual" = "$expected" ]; then
        pass "$label"
    else
        fail "$label" "expected HTTP $expected, got $actual — body: $body"
    fi
}

# Run curl; outputs "STATUS BODY" separated by a newline
curl_json() {
    curl -s -w "\n%{http_code}" -H "Content-Type: application/json" "$@"
}

# ─── Generate a customer JWT inside the commerce container ───────────────────
echo "── Generating JWT token..."
# Unique sub per run so each invocation gets its own rate-limit bucket.
# reservation-write limit is 5 req / 60 s per customer identity; reusing the
# same sub across rapid successive runs would hit 429 on the second run.
RUN_ID=$(date +%s)
TOKEN=$(docker compose -f "$COMPOSE_FILE" exec -T commerce python3 -c "
import jwt, time
print(jwt.encode(
    {'sub': 'test-invariants-$RUN_ID', 'scope': 'customer',
     'exp': int(time.time()) + 3600, 'iat': int(time.time())},
    '$JWT_SECRET', algorithm='HS256'
))
" 2>/dev/null | tr -d '\r\n')

if [ -z "$TOKEN" ]; then
    _red "ERROR: failed to generate JWT — is 'make up' running?"
    exit 1
fi
_green "  token generated"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  HEALTH CHECKS"
echo "═══════════════════════════════════════════════════════"

# Commerce health
RESP=$(curl_json "$COMMERCE/health")
STATUS=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "commerce /health → 200" "200" "$STATUS" "$BODY"

# ERP health (via internal network — no debug profile needed)
ERP_HEALTH=$(docker compose -f "$COMPOSE_FILE" exec -T commerce \
    python3 -c "import urllib.request; r=urllib.request.urlopen('http://erp:8001/health'); print(r.status)" 2>/dev/null | tr -d '\r\n')
if [ "$ERP_HEALTH" = "200" ]; then
    pass "erp /health → 200 (via internal network)"
else
    fail "erp /health → 200 (via internal network)" "got $ERP_HEALTH"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  GOLD-PUSH  ERP → Commerce gold price bridge"
echo "═══════════════════════════════════════════════════════"

# Push a fresh price and verify Commerce stored it
OLD_PRICE=195.50
NEW_PRICE=198.75
RESP=$(curl_json -X POST "$COMMERCE/api/internal/gold-price" \
    -H "X-Internal-Secret: $INTERNAL_SECRET" \
    -d "{\"price\":$NEW_PRICE}")
STATUS=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "GOLD-PUSH  push new price → 201" "201" "$STATUS" "$BODY"

STORED=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('price',''))" 2>/dev/null || echo "")
if [ "$STORED" = "$NEW_PRICE" ]; then
    pass "GOLD-PUSH  response.price == $NEW_PRICE"
else
    fail "GOLD-PUSH  response.price == $NEW_PRICE" "got: $STORED"
fi

# Verify wrong secret is rejected (Law 1 / Law 3)
RESP=$(curl_json -X POST "$COMMERCE/api/internal/gold-price" \
    -H "X-Internal-Secret: wrong-secret" \
    -d "{\"price\":100.0}")
STATUS=$(echo "$RESP" | tail -1)
assert_status "GOLD-PUSH  wrong secret → 401" "401" "$STATUS" ""

# Restore original price so subsequent tests use a known baseline
docker compose -f "$COMPOSE_FILE" exec -T postgres-commerce \
    psql -U commerce -d yasargold_commerce \
    -c "DELETE FROM gold_price WHERE price = $NEW_PRICE;" \
    > /dev/null

echo ""
echo "── Clearing rate-limit buckets for reservation-write..."
# The reservation endpoint is rate-limited to 5 req/60 s per source IP.
# Without clearing, the second consecutive run hits 429 (3 reservation
# attempts per run × 2 runs = 6 > 5). This is a local-testing flush only;
# the rate limiter itself is not under test here.
docker compose -f "$COMPOSE_FILE" exec -T redis \
    redis-cli --scan --pattern "rate:reservation-write:*" \
    | xargs -r docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli DEL \
    > /dev/null 2>&1 || true
_green "  reservation-write rate buckets cleared"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  INV-4 (A) online reservation blocks POS claim"
echo "═══════════════════════════════════════════════════════"

# Refresh gold price to FRESH before this test.
# gold_price.date is stored as UTC (naive). Without a refresh a stack running
# > 90 s after make reset will have a STALE price → 422 QUOTE_STATUS_INVALID.
docker compose -f "$COMPOSE_FILE" exec -T postgres-commerce \
    psql -U commerce -d yasargold_commerce \
    -c "UPDATE gold_price SET date = NOW() WHERE id = 1" \
    > /dev/null
_green "  gold price refreshed (FRESH window reset)"

# Expire any leftover reservation on ITEM_A from a previous run.
# There's no reservation cancel endpoint; we expire via psql so the next
# reservation attempt doesn't hit ITEM_ALREADY_RESERVED.
docker compose -f "$COMPOSE_FILE" exec -T postgres-commerce \
    psql -U commerce -d yasargold_commerce \
    -c "UPDATE reservations SET valid_until = NOW() - INTERVAL '1 second', status = 'EXPIRED' WHERE item_id = $ITEM_A AND status = 'ACTIVE'" \
    > /dev/null

# Step 1: create online reservation for ITEM_A
RESP=$(curl_json -X POST "$COMMERCE/api/v1/reservations" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"item_slug\":\"i-$(printf '%06d' $ITEM_A)\"}")
STATUS=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "INV-4A  create reservation item $ITEM_A → 201" "201" "$STATUS" "$BODY"

# Step 2: POS claim on the same item must be blocked
RESP=$(curl_json -X POST "$COMMERCE/api/v1/items/$ITEM_A/pos-claim" \
    -H "X-POS-Secret: $POS_SECRET" \
    -d '{"ttl_seconds":30}')
STATUS=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "INV-4A  pos-claim while reserved → 409" "409" "$STATUS" "$BODY"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  INV-4 (B) POS claim blocks online reservation"
echo "═══════════════════════════════════════════════════════"

# Step 1: create POS claim for ITEM_B
RESP=$(curl_json -X POST "$COMMERCE/api/v1/items/$ITEM_B/pos-claim" \
    -H "X-POS-Secret: $POS_SECRET" \
    -d '{"ttl_seconds":60}')
STATUS=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "INV-4B  create pos-claim item $ITEM_B → 201" "201" "$STATUS" "$BODY"
CLAIM_B=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['claim_id'])" 2>/dev/null || echo "")

# Step 2: online reservation on the same item must be blocked
RESP=$(curl_json -X POST "$COMMERCE/api/v1/reservations" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"item_slug\":\"i-$(printf '%06d' $ITEM_B)\"}")
STATUS=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "INV-4B  reservation while pos-claimed → 409" "409" "$STATUS" "$BODY"

# Clean up: release the POS claim so the item is available for future runs
if [ -n "$CLAIM_B" ]; then
    curl -s -X DELETE "$COMMERCE/api/v1/items/$ITEM_B/pos-claim/$CLAIM_B" \
        -H "X-POS-Secret: $POS_SECRET" > /dev/null
    _green "  cleanup  pos-claim $CLAIM_B released"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ATOMICITY  concurrent POS claims on item $ITEM_C"
echo "═══════════════════════════════════════════════════════"

# Fire two concurrent claims; use temp files to capture both responses
TMP1=$(mktemp); TMP2=$(mktemp)
curl -s -w "\n%{http_code}" -X POST "$COMMERCE/api/v1/items/$ITEM_C/pos-claim" \
    -H "Content-Type: application/json" \
    -H "X-POS-Secret: $POS_SECRET" \
    -d '{"ttl_seconds":30}' > "$TMP1" &
curl -s -w "\n%{http_code}" -X POST "$COMMERCE/api/v1/items/$ITEM_C/pos-claim" \
    -H "Content-Type: application/json" \
    -H "X-POS-Secret: $POS_SECRET" \
    -d '{"ttl_seconds":30}' > "$TMP2" &
wait

S1=$(tail -1 "$TMP1"); B1=$(head -1 "$TMP1")
S2=$(tail -1 "$TMP2"); B2=$(head -1 "$TMP2")
rm -f "$TMP1" "$TMP2"

WINS=0; LOSSES=0
[ "$S1" = "201" ] && WINS=$((WINS+1))
[ "$S2" = "201" ] && WINS=$((WINS+1))
[ "$S1" = "409" ] && LOSSES=$((LOSSES+1))
[ "$S2" = "409" ] && LOSSES=$((LOSSES+1))

if [ "$WINS" = "1" ] && [ "$LOSSES" = "1" ]; then
    pass "ATOMICITY  exactly one 201 and one 409"
else
    fail "ATOMICITY  exactly one 201 and one 409" \
        "got statuses $S1 and $S2 (expected one of each)"
fi

# Clean up: release whichever claim won
WIN_BODY=""
[ "$S1" = "201" ] && WIN_BODY="$B1"
[ "$S2" = "201" ] && WIN_BODY="$B2"
WIN_CLAIM=$(echo "$WIN_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['claim_id'])" 2>/dev/null || echo "")
if [ -n "$WIN_CLAIM" ]; then
    curl -s -X DELETE "$COMMERCE/api/v1/items/$ITEM_C/pos-claim/$WIN_CLAIM" \
        -H "X-POS-Secret: $POS_SECRET" > /dev/null
    _green "  cleanup  pos-claim $WIN_CLAIM released"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  INV-8  STALE gold price blocks reservation"
echo "═══════════════════════════════════════════════════════"

# Force price STALE by backdating it 10 minutes
docker compose -f "$COMPOSE_FILE" exec -T postgres-commerce \
    psql -U commerce -d yasargold_commerce \
    -c "UPDATE gold_price SET date = NOW() - INTERVAL '10 minutes' WHERE id = 1" \
    > /dev/null
_green "  gold price forced STALE (backdated 10 min)"

RESP=$(curl_json -X POST "$COMMERCE/api/v1/reservations" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"item_slug\":\"i-$(printf '%06d' $ITEM_A)\"}")
STATUS=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "INV-8  reservation with STALE price → 422" "422" "$STATUS" "$BODY"

# Verify the rejection code — the system must name the reason, not silently fail
CODE=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail',{}).get('code',''))" 2>/dev/null || echo "")
if [ "$CODE" = "QUOTE_STATUS_INVALID" ]; then
    pass "INV-8  detail.code == QUOTE_STATUS_INVALID"
else
    fail "INV-8  detail.code == QUOTE_STATUS_INVALID" "got: $CODE"
fi

# Restore FRESH so subsequent runs start clean
docker compose -f "$COMPOSE_FILE" exec -T postgres-commerce \
    psql -U commerce -d yasargold_commerce \
    -c "UPDATE gold_price SET date = NOW() WHERE id = 1" \
    > /dev/null
_green "  gold price restored FRESH"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  N4-IDEM  ERP internal sync idempotency"
echo "  (requires make up-debug; skip otherwise)"
echo "═══════════════════════════════════════════════════════"

# Check debug port is reachable before attempting
if ! curl -sf "$ERP_DEBUG/health" > /dev/null 2>&1; then
    _green "  SKIP  ERP debug port not reachable (run: make up-debug)"
else
    # Reset ITEM_D stock and remove any prior test invoices so this test is
    # idempotent across runs. Each run uses a unique order_id so without this
    # reset the ERP item goes out of stock after N runs (stock=4 / run cost=1).
    # Must delete invoice_item children before invoice (FK constraint)
    docker compose -f "$COMPOSE_FILE" exec -T postgres-erp \
        psql -U erp -d yasargold_erp \
        -c "DELETE FROM invoice_item WHERE invoice_id IN (SELECT id FROM invoice WHERE commerce_order_id LIKE 'test-order-%');
            DELETE FROM invoice WHERE commerce_order_id LIKE 'test-order-%';
            UPDATE item SET stock = 4 WHERE id = $ITEM_D;" \
        > /dev/null
    _green "  reset  item $ITEM_D stock=4, test invoices removed"

    ORDER_ID="test-order-$(date +%s)"
    PAYLOAD="{\"order_id\":\"$ORDER_ID\",\"item_id\":$ITEM_D,\"amount\":1640.0,\"currency\":\"SAR\"}"

    # First call: must create
    RESP=$(curl_json -X POST "$ERP_DEBUG/api/internal/online-orders" \
        -H "X-Internal-Secret: $INTERNAL_SECRET" \
        -d "$PAYLOAD")
    STATUS=$(echo "$RESP" | tail -1)
    BODY=$(echo "$RESP" | head -1)
    assert_status "N4-IDEM  first sync call → 201" "201" "$STATUS" "$BODY"

    # Second call (same order_id): must be idempotent
    RESP=$(curl_json -X POST "$ERP_DEBUG/api/internal/online-orders" \
        -H "X-Internal-Secret: $INTERNAL_SECRET" \
        -d "$PAYLOAD")
    STATUS=$(echo "$RESP" | tail -1)
    BODY=$(echo "$RESP" | head -1)
    assert_status "N4-IDEM  duplicate sync call → 200 already_processed" "200" "$STATUS" "$BODY"

    # Verify the response says already_processed
    SYNC_STATUS=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
    if [ "$SYNC_STATUS" = "already_processed" ]; then
        pass "N4-IDEM  body.status == already_processed"
    else
        fail "N4-IDEM  body.status == already_processed" "got: $SYNC_STATUS"
    fi

    # Wrong secret must be rejected
    RESP=$(curl_json -X POST "$ERP_DEBUG/api/internal/online-orders" \
        -H "X-Internal-Secret: wrong-secret" \
        -d "$PAYLOAD")
    STATUS=$(echo "$RESP" | tail -1)
    assert_status "N4-IDEM  wrong secret → 403" "403" "$STATUS" ""
fi

echo ""
echo "═══════════════════════════════════════════════════════"
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "═══════════════════════════════════════════════════════"

[ "$FAIL" -eq 0 ] && _green "  ALL PASS" || { _red "  FAILURES: $FAIL"; exit 1; }
