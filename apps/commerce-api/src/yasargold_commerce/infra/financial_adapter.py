"""Marker base class for non-production financial adapters.

Any stub or log-only adapter that handles a financial operation (refund, payment,
payout) MUST inherit from NonProductionFinancialAdapter.

The Law 7 boot check in main.py tests isinstance(gateway, NonProductionFinancialAdapter),
not a specific class name. A future LogPaymentGateway or LogPayoutAdapter is caught
automatically without touching the boot check.

Convention (enforced by code review + Law 7 test):
    class LogXxxGateway(NonProductionFinancialAdapter):
        ...

Why a marker and not a flag attribute?
    isinstance() is checked by the boot guard, which runs at lifespan startup before
    any request. An attribute (is_production_safe=False) can be set on an instance
    after construction and is easier to accidentally override. A class-level marker
    makes the non-production declaration part of the type, not the value.
"""


class NonProductionFinancialAdapter:
    """Marker: this adapter is a dev/test stub — not safe for production use.

    Inheriting from this class registers the adapter with the Law 7 boot guard.
    Production environments (COMMERCE_ENV=production) will refuse to start if
    any gateway passed to _check_production_refund_gateway_config() is an
    instance of this class.

    No methods — pure marker. isinstance() is the enforcement mechanism.
    """
