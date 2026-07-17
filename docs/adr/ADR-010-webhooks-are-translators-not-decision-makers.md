# ADR-010: External Webhooks Are Translators, Not Decision-Makers

**Status**: Accepted  
**Date**: 2026-07-13

## Rule

The HTTP webhook handler translates an external event into a `WebhookResult`
domain value object. All state transition decisions happen inside domain
services. The handler never contains `if paid:` or `if failed:` branching.

## Context

Without this rule, webhook handlers accumulate business logic over time:

```python
# BAD — state machine leaking into HTTP layer
@app.post("/webhooks/payment")
async def payment_webhook(body: dict):
    if body["status"] == "paid":
        reservation = db.get(body["metadata"]["reservation_id"])
        reservation.status = "COMPLETED"  # direct mutation, bypasses domain
        db.commit()
    elif body["status"] == "failed":
        # retry logic, notification logic — all here
        ...
```

This creates three separate sources of truth: the handler, the domain service,
and the ORM model. When business rules change (e.g. "authorized" counts as
paid), the fix must happen in every handler that checks the status string.

## Decision

The webhook handler does exactly three things:

```
1. Verify provider signature          → gateway.parse_webhook()
2. Translate to WebhookResult         → gateway.parse_webhook()
3. Pass to domain service             → PaymentService.confirm(webhook_result)
```

```python
# CORRECT — handler is a thin translator
@router.post("/webhooks/payment", status_code=204)
async def payment_webhook(request: Request, ...):
    payload = await request.body()
    webhook_result = gateway.parse_webhook(payload, signature)   # translate
    intent = payment_service.confirm(webhook_result, uow)        # domain decides
    if intent.can_confirm():
        checkout_service.confirm(intent.reservation_id, ...)     # domain decides
```

The domain decides:
  - Whether "authorized" counts as "paid" (`_PAID_STATUSES` in `moyasar_gateway.py`)
  - Whether the intent can transition (`PaymentIntent.can_pay()`)
  - Whether the reservation can be confirmed (`CheckoutService.confirm()`)

The handler never decides.

## What "translation" means

| Allowed in handler | Not allowed in handler |
|-|-|
| Verify HMAC signature | Check payment status string |
| Parse raw bytes → `WebhookResult` | Decide if status is terminal |
| Call domain service | Update ORM models directly |
| Map domain exceptions → HTTP codes | Re-implement business rules |
| Record Prometheus metrics | Branch on provider-specific fields |

## Idempotency contract

The handler must return `204` for:
  - Duplicate webhooks (already PAID/FAILED) → `PaymentIntentStatusError` → 204
  - Late webhooks after expiry → `PaymentIntentExpiredError` → 204
  - Already confirmed reservations → `ReservationStatusError` → 204

The domain services enforce these guards. The handler maps exceptions to 204,
never to 200 with a custom payload.

## Scope

This rule applies to all external event handlers, not only payment webhooks:

| Future capability | Handler receives | Domain decides |
|-|-|-|
| Shipping webhook | TrackingEvent (translated) | ShipmentService |
| SMS delivery receipt | DeliveryResult (translated) | NotificationService |
| Gold price feed | PriceTick (translated) | PricingEngine |

When adding a new external event source:
1. Define a value object in `packages/domain` (e.g. `TrackingEvent`)
2. Translate in the Adapter (`ShipmentGateway.parse_event()`)
3. Pass to domain service — no branching in the handler

## Enforcement

Any PR where a webhook handler contains `if status == "..."` or direct ORM
writes must be rejected in review citing this ADR.
