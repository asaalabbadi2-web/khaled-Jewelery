"""Law 7 proof tests — Financial Adapter boot guard (E3 + A1).

Law 7 — No Financial Adapter may silently downgrade in Production.
  LogRefundGateway logs and returns immediately; real refunds are silently
  skipped. Misconfiguration must fail at boot, not at the first customer refund.

Coverage matrix — _build_refund_gateway() + _check_production_refund_gateway_config():

  GW1: Production + MOYASAR_SECRET_KEY set
       → MoyasarRefundGateway built; check passes; app boots.
  GW2: Production + MOYASAR_SECRET_KEY absent
       → LogRefundGateway built; check raises RuntimeError; boot fails.
  GW3: Production + LogRefundGateway wired explicitly
       → check raises RuntimeError regardless of how the gateway was built.
  GW4: Development + no MOYASAR_SECRET_KEY
       → LogRefundGateway allowed; check passes; WARNING logged.
  GW5: COMMERCE_ENV=test + no MOYASAR_SECRET_KEY
       → LogRefundGateway allowed; check passes.
  GW6: Development + MOYASAR_SECRET_KEY set
       → MoyasarRefundGateway built; check passes.
  GW7: Production + NEW stub subclassing NonProductionFinancialAdapter
       → check raises RuntimeError. Proves the marker catches future adapters
       without modifying the boot guard (no class-name whack-a-mole).

Law 0 requirement: every test here must be RED before the implementation exists,
GREEN after. GW2, GW3, and GW7 are the load-bearing cases — they prove the real
failure mode is caught at boot, not per-refund, and that the marker generalises.
"""
from __future__ import annotations

import logging

import pytest


# ---------------------------------------------------------------------------
# GW1 — Production + key present → MoyasarRefundGateway, boot OK
# ---------------------------------------------------------------------------

class TestGW1ProductionWithKey:
    def test_build_returns_moyasar_gateway(self, monkeypatch) -> None:
        monkeypatch.setenv("MOYASAR_SECRET_KEY", "sk_live_testkey")
        monkeypatch.setenv("COMMERCE_ENV", "production")

        from yasargold_commerce.main import _build_refund_gateway
        from yasargold_commerce.infra.moyasar_refund_gateway import MoyasarRefundGateway

        gw = _build_refund_gateway()
        assert isinstance(gw, MoyasarRefundGateway)

    def test_check_does_not_raise(self, monkeypatch) -> None:
        monkeypatch.setenv("MOYASAR_SECRET_KEY", "sk_live_testkey")
        monkeypatch.setenv("COMMERCE_ENV", "production")

        from yasargold_commerce.main import _build_refund_gateway, _check_production_refund_gateway_config

        gw = _build_refund_gateway()
        _check_production_refund_gateway_config(gw)  # must not raise


# ---------------------------------------------------------------------------
# GW2 — Production + key absent → LogRefundGateway built → boot fails
# ---------------------------------------------------------------------------

class TestGW2ProductionNoKey:
    def test_build_returns_log_gateway_when_key_absent(self, monkeypatch) -> None:
        monkeypatch.delenv("MOYASAR_SECRET_KEY", raising=False)

        from yasargold_commerce.main import _build_refund_gateway
        from yasargold_commerce.infra.log_refund_gateway import LogRefundGateway

        gw = _build_refund_gateway()
        assert isinstance(gw, LogRefundGateway)

    def test_check_raises_in_production(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "production")
        monkeypatch.delenv("MOYASAR_SECRET_KEY", raising=False)

        from yasargold_commerce.main import _build_refund_gateway, _check_production_refund_gateway_config

        gw = _build_refund_gateway()
        with pytest.raises(RuntimeError, match="LogRefundGateway"):
            _check_production_refund_gateway_config(gw)

    def test_error_message_names_the_fix(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "production")
        monkeypatch.delenv("MOYASAR_SECRET_KEY", raising=False)

        from yasargold_commerce.main import _build_refund_gateway, _check_production_refund_gateway_config

        gw = _build_refund_gateway()
        with pytest.raises(RuntimeError, match="MOYASAR_SECRET_KEY"):
            _check_production_refund_gateway_config(gw)


# ---------------------------------------------------------------------------
# GW3 — Production + explicit LogRefundGateway → boot fails
# (type-check, not credential-check: even if someone wires it wrong in code)
# ---------------------------------------------------------------------------

class TestGW3ProductionExplicitLogGateway:
    def test_check_raises_on_log_gateway_instance(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "production")

        from yasargold_commerce.main import _check_production_refund_gateway_config
        from yasargold_commerce.infra.log_refund_gateway import LogRefundGateway

        with pytest.raises(RuntimeError, match="LogRefundGateway"):
            _check_production_refund_gateway_config(LogRefundGateway())

    def test_error_cites_law(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "production")

        from yasargold_commerce.main import _check_production_refund_gateway_config
        from yasargold_commerce.infra.log_refund_gateway import LogRefundGateway

        with pytest.raises(RuntimeError, match="Law 7"):
            _check_production_refund_gateway_config(LogRefundGateway())


# ---------------------------------------------------------------------------
# GW4 — Development + no key → LogRefundGateway allowed, WARNING logged
# ---------------------------------------------------------------------------

class TestGW4DevelopmentLogGateway:
    def test_check_does_not_raise_in_development(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "development")
        monkeypatch.delenv("MOYASAR_SECRET_KEY", raising=False)

        from yasargold_commerce.main import _check_production_refund_gateway_config
        from yasargold_commerce.infra.log_refund_gateway import LogRefundGateway

        _check_production_refund_gateway_config(LogRefundGateway())  # must not raise

    def test_build_logs_warning_when_key_absent(self, monkeypatch, caplog) -> None:
        monkeypatch.delenv("MOYASAR_SECRET_KEY", raising=False)

        from yasargold_commerce.main import _build_refund_gateway

        with caplog.at_level(logging.WARNING, logger="yasargold_commerce.main"):
            _build_refund_gateway()

        assert any("LogRefundGateway" in r.message for r in caplog.records), (
            "A WARNING naming LogRefundGateway must be emitted when MOYASAR_SECRET_KEY is absent"
        )


# ---------------------------------------------------------------------------
# GW5 — COMMERCE_ENV=test + no key → LogRefundGateway allowed
# ---------------------------------------------------------------------------

class TestGW5TestEnvLogGateway:
    def test_check_does_not_raise_in_test_env(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "test")
        monkeypatch.delenv("MOYASAR_SECRET_KEY", raising=False)

        from yasargold_commerce.main import _check_production_refund_gateway_config
        from yasargold_commerce.infra.log_refund_gateway import LogRefundGateway

        _check_production_refund_gateway_config(LogRefundGateway())  # must not raise

    def test_check_does_not_raise_when_env_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("COMMERCE_ENV", raising=False)
        monkeypatch.delenv("MOYASAR_SECRET_KEY", raising=False)

        from yasargold_commerce.main import _check_production_refund_gateway_config
        from yasargold_commerce.infra.log_refund_gateway import LogRefundGateway

        _check_production_refund_gateway_config(LogRefundGateway())  # must not raise


# ---------------------------------------------------------------------------
# GW6 — Development + key present → MoyasarRefundGateway, no error
# ---------------------------------------------------------------------------

class TestGW6DevelopmentWithKey:
    def test_build_returns_moyasar_in_development(self, monkeypatch) -> None:
        monkeypatch.setenv("MOYASAR_SECRET_KEY", "sk_dev_testkey")
        monkeypatch.setenv("COMMERCE_ENV", "development")

        from yasargold_commerce.main import _build_refund_gateway
        from yasargold_commerce.infra.moyasar_refund_gateway import MoyasarRefundGateway

        gw = _build_refund_gateway()
        assert isinstance(gw, MoyasarRefundGateway)

    def test_check_does_not_raise_for_moyasar_in_development(self, monkeypatch) -> None:
        monkeypatch.setenv("MOYASAR_SECRET_KEY", "sk_dev_testkey")
        monkeypatch.setenv("COMMERCE_ENV", "development")

        from yasargold_commerce.main import _build_refund_gateway, _check_production_refund_gateway_config

        gw = _build_refund_gateway()
        _check_production_refund_gateway_config(gw)  # must not raise


# ---------------------------------------------------------------------------
# GW7 — Production + any new stub inheriting NonProductionFinancialAdapter
#        → blocked without modifying the boot guard (marker generality proof)
# ---------------------------------------------------------------------------

class TestGW7MarkerCatchesFutureAdapters:
    def test_new_stub_subclass_blocked_in_production(self, monkeypatch) -> None:
        """A brand-new LogPaymentGatewayStub that was never mentioned in main.py
        is blocked purely because it inherits NonProductionFinancialAdapter.
        This is the anti-whack-a-mole proof required by A1."""
        monkeypatch.setenv("COMMERCE_ENV", "production")

        from yasargold_commerce.infra.financial_adapter import NonProductionFinancialAdapter
        from yasargold_commerce.main import _check_production_refund_gateway_config

        class LogPaymentGatewayStub(NonProductionFinancialAdapter):
            """Hypothetical future stub — never imported in main.py."""

        with pytest.raises(RuntimeError, match="LogPaymentGatewayStub"):
            _check_production_refund_gateway_config(LogPaymentGatewayStub())

    def test_error_still_cites_law(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "production")

        from yasargold_commerce.infra.financial_adapter import NonProductionFinancialAdapter
        from yasargold_commerce.main import _check_production_refund_gateway_config

        class LogPayoutAdapterStub(NonProductionFinancialAdapter):
            pass

        with pytest.raises(RuntimeError, match="Law 7"):
            _check_production_refund_gateway_config(LogPayoutAdapterStub())
