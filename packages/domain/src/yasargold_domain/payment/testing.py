"""FakePaymentGateway / FakeRefundGateway — in-memory stubs for domain tests.

ADR-009: External Providers Are Adapters.
ADR-019: Every Protocol must have a Fake in {capability}/testing.py.

This module is the ONLY place in packages/domain that knows the word "fake" or
"stub". It exists so that:
  1. Domain tests (packages/domain/tests/) run with zero network calls.
  2. Commerce API integration tests can import and reuse the same stub.
  3. No real Adapter (MoyasarGateway, TapGateway) ever enters this package.

Usage in tests:
    from yasargold_domain.payment.testing import FakePaymentGateway

    gateway = FakePaymentGateway()
    service = PaymentService(gateway)
    intent, url = service.issue(...)
    assert url == gateway.last_checkout_url

Configuration:
    gateway = FakePaymentGateway(
        checkout_url="https://pay.example.com/test",
        provider_reference="pay_fake_abc123",
    )

Forced failures (for error-path tests):
    gateway = FakePaymentGateway(fail_on_initiate=True)
    with pytest.raises(RuntimeError):
        service.issue(...)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from yasargold_domain.payment.gateway import CheckoutUrl, PaymentGateway, WebhookResult
from yasargold_domain.payment.intent import PaymentIntent
from yasargold_domain.shared.identifiers import PaymentFailureReason


@dataclass
class FakePaymentGateway:
    """In-memory implementation of PaymentGateway.

    Structurally satisfies the PaymentGateway Protocol (duck typing) —
    no inheritance required.

    Attributes:
        checkout_url:       URL returned by initiate() — configurable per test.
        provider_reference: Reference token returned by initiate() — configurable.
        fail_on_initiate:   If True, initiate() raises RuntimeError.
        fail_on_webhook:    If True, parse_webhook() raises RuntimeError.
        webhook_outcome:    "paid" | "failed" — drives parse_webhook() result.
        webhook_failure_reason: Returned when webhook_outcome == "failed".

    Recorded calls (for assertions):
        initiated:  list of (intent, callback_url) pairs passed to initiate().
        parsed:     list of (payload, signature) pairs passed to parse_webhook().
    """

    checkout_url: str = "https://pay.fake-gateway.example/checkout/test-session"
    provider_reference: str = "pay_fake_0000000000000001"
    fail_on_initiate: bool = False
    fail_on_webhook: bool = False
    webhook_outcome: Literal["paid", "failed"] = "paid"
    webhook_failure_reason: PaymentFailureReason | None = None

    initiated: list[tuple[PaymentIntent, str]] = field(default_factory=list)
    parsed: list[tuple[bytes, str]] = field(default_factory=list)

    def initiate(self, intent: PaymentIntent, callback_url: str) -> CheckoutUrl:
        """Return a deterministic CheckoutUrl. Raises if fail_on_initiate is set."""
        if self.fail_on_initiate:
            raise RuntimeError("FakePaymentGateway: simulated initiate failure")
        self.initiated.append((intent, callback_url))
        return CheckoutUrl(
            url=self.checkout_url,
            provider_reference=self.provider_reference,
        )

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookResult:
        """Return a deterministic WebhookResult. Raises if fail_on_webhook is set."""
        if self.fail_on_webhook:
            raise RuntimeError("FakePaymentGateway: simulated webhook parse failure")
        self.parsed.append((payload, signature))
        return WebhookResult(
            provider_reference=self.provider_reference,
            outcome=self.webhook_outcome,
            paid_at=datetime.now(timezone.utc) if self.webhook_outcome == "paid" else None,
            failure_reason=self.webhook_failure_reason,
        )

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    @property
    def last_checkout_url(self) -> str | None:
        """The URL from the most recent initiate() call, or None."""
        return self.checkout_url if self.initiated else None

    @property
    def initiate_count(self) -> int:
        """Number of times initiate() was called."""
        return len(self.initiated)

    @property
    def parse_count(self) -> int:
        """Number of times parse_webhook() was called."""
        return len(self.parsed)


# ---------------------------------------------------------------------------
# FakeRefundGateway — ADR-019 fake for the RefundGateway Protocol
# ---------------------------------------------------------------------------

from yasargold_domain.payment.refund_gateway import RefundPermanentError, RefundTransientError  # noqa: E402


@dataclass
class FakeRefundGateway:
    """In-memory implementation of RefundGateway (ADR-019).

    Records every refund call. Configurable to simulate transient or permanent
    failures on the next call (self-clearing after each fire).

    Attributes:
        fail_transient_on_next:  If True, next refund() raises RefundTransientError.
        fail_permanent_on_next:  If True, next refund() raises RefundPermanentError.
        refunds:                 List of intents passed to refund() that succeeded.
    """

    fail_transient_on_next: bool = False
    fail_permanent_on_next: bool = False
    refunds: list[PaymentIntent] = field(default_factory=list)

    def refund(self, intent: PaymentIntent) -> None:
        if self.fail_permanent_on_next:
            self.fail_permanent_on_next = False
            raise RefundPermanentError("FakeRefundGateway: simulated permanent failure")
        if self.fail_transient_on_next:
            self.fail_transient_on_next = False
            raise RefundTransientError("FakeRefundGateway: simulated transient failure")
        self.refunds.append(intent)

    @property
    def refund_count(self) -> int:
        """Number of successful refund() calls."""
        return len(self.refunds)
