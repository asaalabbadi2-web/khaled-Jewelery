"""LogRefundGateway — development stub for the RefundGateway Protocol.

Logs every refund call and returns immediately (simulates success).
Replace with MoyasarRefundGateway before going to Gate A.

SEC-002 equivalent for refunds: a sandbox test proving that the real adapter
calls the correct Moyasar endpoint with the correct provider_reference must
be a merge requirement before any production adapter is merged.
"""
from __future__ import annotations

import logging

from yasargold_domain.payment.intent import PaymentIntent
from yasargold_commerce.infra.financial_adapter import NonProductionFinancialAdapter

log = logging.getLogger(__name__)


class LogRefundGateway(NonProductionFinancialAdapter):
    """Logs the refund call; never actually contacts a payment provider."""

    def refund(self, intent: PaymentIntent) -> None:
        log.info(
            "log_refund_gateway: REFUND intent=%s provider_ref=%s amount=%s %s",
            intent.id,
            intent.provider_reference,
            intent.amount,
            intent.currency,
        )
