"""Order domain exceptions.

HTTP mapping (enforced in the router, never in the domain):
    OrderNotFoundException  → 404
    OrderStatusError        → 409
"""
from __future__ import annotations


class OrderNotFoundException(Exception):
    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        super().__init__(f"Order not found: {order_id}")


class OrderStatusError(Exception):
    def __init__(
        self,
        order_id: str,
        *,
        current_status: str,
        expected: str,
    ) -> None:
        self.order_id = order_id
        self.current_status = current_status
        self.expected = expected
        super().__init__(
            f"Order {order_id} is {current_status!r}, expected {expected!r}"
        )
