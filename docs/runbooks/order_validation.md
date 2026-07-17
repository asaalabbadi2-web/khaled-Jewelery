# Runbook: Order Domain Validation Gates

**Sprint:** 5  
**Date:** 2026-07-13  
**Purpose:** Validate the complete Order flow before enabling downstream capabilities
(Shipping, Notifications, ERP Sync).

Run these gates in order. All gates must pass before marking Sprint 5 complete.

---

## Prerequisites

Sprint 4 (Payment) gates must have passed. Orders depend on PaymentIntents.

---

## Gate 1 — Webhook Creates Order

**What it proves:** The full chain POST /webhooks/payment → Order(CONFIRMED) +
Reservation(COMPLETED) runs atomically.

```bash
# (Re-use Sprint 4 Gate 2 steps to create a PaymentIntent first)
# Then send a valid webhook:
PAYLOAD='{"id":"pay_sprint5_test","status":"paid","amount":550000,"currency":"SAR","paid_at":"2026-07-13T14:05:00+00:00","updated_at":"2026-07-13T14:05:00+00:00"}'
SIG=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$MOYASAR_SECRET_KEY" | awk '{print $2}')

curl -s -X POST http://localhost:8001/api/v1/webhooks/payment \
  -H "Content-Type: application/json" \
  -H "X-Moyasar-Signature: $SIG" \
  -d "$PAYLOAD"
```

**Expected response:** `204 No Content`

**Check orders table:**
```sql
SELECT id, reservation_id, payment_intent_id, status, confirmed_at
FROM orders WHERE reservation_id = '<reservation_id>';
-- Expected: one row, status = 'CONFIRMED', confirmed_at IS NOT NULL
```

**Check reservation:**
```sql
SELECT status FROM reservations WHERE id = '<reservation_id>';
-- Expected: status = 'COMPLETED'
```

**Check outbox (both events in one commit):**
```sql
SELECT event_type FROM outbox_events
WHERE event_type LIKE '%Order%' OR event_type LIKE '%ReservationConfirmed%'
ORDER BY id DESC LIMIT 5;
-- Expected: OrderCreated + ReservationConfirmed (same transaction, adjacent IDs)
```

**Check metrics:**
```
order_created_total > 0
reservation_confirmed_total > 0
```

**Gate 1 passes when:** 204, `orders` row exists with CONFIRMED, reservation COMPLETED,
both events in outbox, metrics recorded.

---

## Gate 2 — GET /orders/{order_id} Returns 200

**What it proves:** The Order is readable via the API after creation.

```bash
ORDER_ID=$(psql -U postgres yasargold_commerce -t -c \
  "SELECT id FROM orders WHERE reservation_id='<reservation_id>';" | tr -d ' ')

curl -s http://localhost:8001/api/v1/orders/$ORDER_ID | jq .
```

**Expected response (200):**
```json
{
  "order_id": "ord_...",
  "reservation_id": "...",
  "payment_intent_id": "pi_...",
  "item_id": 42,
  "amount": "5500.00",
  "currency": "SAR",
  "status": "CONFIRMED",
  "created_at": "...",
  "confirmed_at": "..."
}
```

**Gate 2 passes when:** 200 received with all required fields.

---

## Gate 3 — GET /reservations/{reservation_id}/order Returns 200

**What it proves:** Downstream capabilities can look up orders by reservation_id.

```bash
curl -s http://localhost:8001/api/v1/reservations/<reservation_id>/order | jq .
```

**Expected response (200):** Same structure as Gate 2.

**Gate 3 passes when:** 200, `order_id` matches the order from Gate 1.

---

## Gate 4 — Order Not Found Returns 404

**What it proves:** Unknown IDs are handled gracefully.

```bash
curl -s http://localhost:8001/api/v1/orders/ord_nonexistent -o /dev/null -w "%{http_code}"
# Expected: 404
```

**Gate 4 passes when:** 404 returned.

---

## Gate 5 — Duplicate Webhook Does Not Create Duplicate Order

**What it proves:** Sending the same webhook twice produces exactly one Order.

```bash
# Resend the same webhook from Gate 1 (same payload, same signature)
curl -s -X POST http://localhost:8001/api/v1/webhooks/payment \
  -H "Content-Type: application/json" \
  -H "X-Moyasar-Signature: $SIG" \
  -d "$PAYLOAD"
# Expected: 204 (idempotent)
```

**Check no duplicate order:**
```sql
SELECT COUNT(*) FROM orders WHERE reservation_id = '<reservation_id>';
-- Expected: COUNT = 1 (not 2)
```

**Gate 5 passes when:** 204, COUNT = 1.

---

## Summary Checklist

| Gate | Description | Status |
|------|-------------|--------|
| Gate 1 | Webhook → Order(CONFIRMED) + Reservation(COMPLETED) atomically | ⬜ |
| Gate 2 | GET /orders/{id} → 200 with full Order data | ⬜ |
| Gate 3 | GET /reservations/{id}/order → 200 | ⬜ |
| Gate 4 | Unknown order_id → 404 | ⬜ |
| Gate 5 | Duplicate webhook → 204, no duplicate Order | ⬜ |

All 5 gates green → Sprint 5 complete → Orders production-ready.

---

## Escalation

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Gate 1 → 500 on webhook | CheckoutUnitOfWork exception | Check logs for OrderService error |
| Gate 1 → Order saved but Reservation not COMPLETED | Non-atomic commit | Verify SQLAlchemyCheckoutUnitOfWork uses same session |
| Gate 1 → Reservation COMPLETED but no Order | Race condition | Should be impossible with shared session |
| Gate 2 → 404 | Orders table not migrated | Run `alembic upgrade orders_001` |
| Gate 5 → duplicate Order | Idempotency bug in CheckoutService | Check `reservation.status != ACTIVE` guard |
