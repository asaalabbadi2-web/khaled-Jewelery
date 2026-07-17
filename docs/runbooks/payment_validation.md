# Runbook: Payment Domain Validation Gates

**Sprint:** 4  
**Date:** 2026-07-13  
**Purpose:** Validate the complete payment flow before enabling for production traffic.

Run these gates in order. Each gate must pass before the next begins.
All gates must pass before marking Sprint 4 complete.

---

## Gate 1 — Create PaymentIntent

**What it proves:** `POST /api/v1/payments` creates an intent, opens a Moyasar
session, and returns a checkout URL.

```bash
curl -s -X POST http://localhost:8001/api/v1/payments \
  -H "Content-Type: application/json" \
  -d '{"reservation_id": "<active_reservation_id>"}' | jq .
```

**Expected response (201):**
```json
{
  "payment_intent_id": "pi_...",
  "checkout_url": "https://api.moyasar.com/v1/payments/.../sources/creditcard",
  "expires_at": "...",
  "provider": "moyasar"
}
```

**Check database:**
```sql
SELECT id, status, provider_reference, amount FROM payment_intents
WHERE reservation_id = '<reservation_id>';
-- Expected: status = 'PENDING', provider_reference = 'pay_...'
```

**Check metrics:**
```
payment_intent_created_total > 0
payment_gateway_request_duration_seconds has observations
```

**Gate 1 passes when:** 201 received, `payment_intents` row exists, metric recorded.

---

## Gate 2 — Valid Webhook → PAID + Reservation COMPLETED

**What it proves:** The full chain works end-to-end.

After completing payment at the Moyasar checkout URL, wait for the webhook
callback. Or simulate with a signed webhook:

```bash
# Build a valid Moyasar webhook payload
PAYLOAD='{"id":"pay_test","status":"paid","amount":550000,"currency":"SAR","paid_at":"2026-07-13T14:05:00+00:00","updated_at":"2026-07-13T14:05:00+00:00"}'
SIG=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$MOYASAR_SECRET_KEY" | awk '{print $2}')

curl -s -X POST http://localhost:8001/api/v1/webhooks/payment \
  -H "Content-Type: application/json" \
  -H "X-Moyasar-Signature: $SIG" \
  -d "$PAYLOAD"
```

**Expected response:** `204 No Content`

**Check database:**
```sql
SELECT status, paid_at FROM payment_intents WHERE provider_reference = 'pay_test';
-- Expected: status = 'PAID', paid_at IS NOT NULL

SELECT status FROM reservations WHERE id = '<reservation_id>';
-- Expected: status = 'COMPLETED'
```

**Check outbox:**
```sql
SELECT event_type FROM outbox_events ORDER BY id DESC LIMIT 5;
-- Expected: PaymentReceived + ReservationConfirmed events present
```

**Check metrics:**
```
payment_received_total > 0
reservation_confirmed_total > 0
reservation_lifetime_seconds{outcome="confirmed"} has observations
payment_webhook_latency_seconds has observations
```

**Gate 2 passes when:** 204 received, both rows updated, all 4 metrics recorded.

---

## Gate 3 — Duplicate Webhook (Idempotency)

**What it proves:** Sending the same webhook twice is safe — 204, no double events.

Resend the exact same webhook from Gate 2 (same payload, same signature):

```bash
# Same command as Gate 2
curl -s -X POST http://localhost:8001/api/v1/webhooks/payment \
  -H "Content-Type: application/json" \
  -H "X-Moyasar-Signature: $SIG" \
  -d "$PAYLOAD"
```

**Expected response:** `204 No Content`

**Check that no extra events were enqueued:**
```sql
SELECT COUNT(*) FROM outbox_events
WHERE event_type LIKE '%PaymentReceived%'
  AND payload::jsonb->>'provider_reference' = 'pay_test';
-- Expected: COUNT = 1 (not 2)
```

**Gate 3 passes when:** 204 received, outbox event count unchanged from Gate 2.

---

## Gate 4 — Expired Intent

**What it proves:** A webhook arriving after `expires_at` is handled gracefully —
no crash, no reservation change, 204 returned.

Create a reservation, let it expire (or use a test intent with past `expires_at`),
then send a paid webhook:

```bash
# Update intent expiry directly for testing
docker exec yasargold-db psql -U postgres yasargold_commerce -c \
  "UPDATE payment_intents SET expires_at = NOW() - INTERVAL '1 hour' WHERE id = '<pi_id>';"

# Send paid webhook
curl -s -X POST http://localhost:8001/api/v1/webhooks/payment \
  -H "Content-Type: application/json" \
  -H "X-Moyasar-Signature: $SIG" \
  -d "$PAYLOAD"
```

**Expected response:** `204 No Content`

**Check that reservation was NOT completed:**
```sql
SELECT status FROM reservations WHERE id = '<reservation_id>';
-- Expected: status = 'ACTIVE' or 'EXPIRED' — NOT 'COMPLETED'
```

**Gate 4 passes when:** 204 received, reservation not promoted to COMPLETED.

---

## Gate 5 — Provider Timeout / Unavailability

**What it proves:** If Moyasar is unreachable, the endpoint returns 502 and
saves nothing — no orphaned intents.

Simulate by temporarily blocking outbound traffic to Moyasar, or by
setting an invalid API key:

```bash
# With invalid key (triggers 401 from Moyasar → 4xx → no retry → 502)
MOYASAR_API_KEY=pk_invalid curl -s -X POST http://localhost:8001/api/v1/payments \
  -H "Content-Type: application/json" \
  -d '{"reservation_id": "<active_reservation_id>"}' -o /dev/null -w "%{http_code}"
# Expected: 502
```

**Check database:**
```sql
SELECT COUNT(*) FROM payment_intents WHERE reservation_id = '<reservation_id>';
-- Expected: COUNT = 0 (nothing saved on gateway failure)
```

**Check metrics:**
```
payment_gateway_failures_total{provider="moyasar"} > 0
```

**Gate 5 passes when:** 502 returned, no row in `payment_intents`, failure metric recorded.

---

## Summary Checklist

| Gate | Description | Status |
|------|-------------|--------|
| Gate 1 | Create PaymentIntent → 201 + row saved | ⬜ |
| Gate 2 | Valid webhook → PAID + COMPLETED + events | ⬜ |
| Gate 3 | Duplicate webhook → 204, no double events | ⬜ |
| Gate 4 | Expired intent webhook → 204, no state change | ⬜ |
| Gate 5 | Gateway failure → 502, nothing saved | ⬜ |

All 5 gates green → Sprint 4 complete → Payment domain production-ready.

---

## Escalation

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Gate 1 → 503 | DB unreachable | Check PostgreSQL connection |
| Gate 1 → 502 | Moyasar API key wrong / network | Check `MOYASAR_API_KEY` env var |
| Gate 2 → 400 | Wrong `MOYASAR_SECRET_KEY` | Verify webhook secret in Moyasar dashboard |
| Gate 2 → 404 | `provider_reference` not found | Check DB: intent row created in Gate 1? |
| Gate 3 → duplicate events | Idempotency bug | See `PaymentService.confirm()` status guard |
| Gate 5 → 500 instead of 502 | Unhandled exception in router | Check error logs for traceback |
