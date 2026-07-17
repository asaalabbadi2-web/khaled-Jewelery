"""Shipping domain capability — manages shipment lifecycle for Orders.

State machine:
    PENDING → CREATED → IN_TRANSIT → DELIVERED (terminal)
                  ↘
                VOIDED (terminal, only from CREATED within void_window)
    PENDING → FAILED  (terminal, if carrier rejects registration)

Design principles (ADR-015):
    - claim-then-send mandatory: caller commits PENDING before network call
    - declared_value frozen at claim time from locked_rate × weight (§13 Frozen)
    - void_window read live from CarrierConfig at decision time (§13 Live)
    - can_void(now, void_window) is a pure function — now is always injected
"""
