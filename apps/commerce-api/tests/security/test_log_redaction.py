"""Security test — Law 2 face 2: secrets never appear in logs (ADR-017).

Law 2 has two faces:
    Face 1: import-linter blocks os.environ / settings imports inside packages/domain
            (already enforced — no new test needed here)
    Face 2: sensitive field values are redacted before they reach any log handler

This test proves Face 2 using RedactingFilter from security.py.

The test does NOT rely on application startup or any HTTP stack. It operates
directly on the logging subsystem, capturing records at the handler level.

Proof requirement:
    A log message that contains "Authorization: Bearer abc123" must reach
    the handler as "Authorization=<redacted>", never as "abc123".
"""
from __future__ import annotations

import logging
from io import StringIO

import pytest

from yasargold_commerce.security import RedactingFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_logger(name: str = "test.redaction") -> tuple[logging.Logger, StringIO]:
    """Return a logger + StringIO that captures its output after redaction."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger, buf


# ---------------------------------------------------------------------------
# Law 2 face 2 — redaction tests
# ---------------------------------------------------------------------------

class TestRedactingFilter:
    def test_authorization_header_value_redacted(self) -> None:
        logger, buf = _make_logger("test.auth_header")
        logger.warning("incoming request headers: authorization: Bearer abc123xyz")
        output = buf.getvalue()
        assert "abc123xyz" not in output
        assert "<redacted>" in output

    def test_x_admin_secret_value_redacted(self) -> None:
        logger, buf = _make_logger("test.admin_secret")
        logger.info("header dump: X-Admin-Secret: supersecret99")
        output = buf.getvalue()
        assert "supersecret99" not in output
        assert "<redacted>" in output

    def test_x_internal_secret_value_redacted(self) -> None:
        logger, buf = _make_logger("test.internal_secret")
        logger.info("erp call headers: X-Internal-Secret: erp_test_key")
        output = buf.getvalue()
        assert "erp_test_key" not in output
        assert "<redacted>" in output

    def test_api_key_value_redacted(self) -> None:
        logger, buf = _make_logger("test.api_key")
        logger.error("gateway error: api_key=sk_live_abc123 status=403")
        output = buf.getvalue()
        assert "sk_live_abc123" not in output
        assert "<redacted>" in output

    def test_token_value_redacted(self) -> None:
        logger, buf = _make_logger("test.token")
        logger.debug("auth context: token=eyJhbGciOiJIUzI1NiJ9")
        output = buf.getvalue()
        assert "eyJhbGciOiJIUzI1NiJ9" not in output
        assert "<redacted>" in output

    def test_non_sensitive_fields_pass_through(self) -> None:
        logger, buf = _make_logger("test.passthrough")
        logger.info("order created: order_id=ord_abc123 amount=5500 currency=SAR")
        output = buf.getvalue()
        assert "ord_abc123" in output
        assert "5500" in output
        assert "SAR" in output

    def test_partial_message_with_sensitive_and_safe_fields(self) -> None:
        logger, buf = _make_logger("test.mixed")
        logger.warning(
            "request: order_id=ord_xyz authorization: Bearer tok_secret item_id=42"
        )
        output = buf.getvalue()
        assert "tok_secret" not in output
        assert "ord_xyz" in output
        assert "42" in output

    def test_non_string_msg_not_crashed(self) -> None:
        logger, buf = _make_logger("test.non_string")
        record = logging.LogRecord(
            name="test", level=logging.WARNING,
            pathname="", lineno=0, msg={"key": "value"},
            args=(), exc_info=None,
        )
        f = RedactingFilter()
        result = f.filter(record)
        assert result is True  # must not raise; non-string msg passes unchanged


# ---------------------------------------------------------------------------
# Prove the filter is installed correctly on the module logger
# (demonstrates the installation pattern — not a property of the module itself)
# ---------------------------------------------------------------------------

class TestRedactingFilterArgs:
    """Law 2 face 2 — secrets in %s / %(name)s args must be redacted."""

    def test_positional_args_tuple_redacted(self) -> None:
        """log.error('header: %s', auth_value) must not emit auth_value."""
        f = RedactingFilter()
        record = logging.LogRecord(
            name="test", level=logging.ERROR,
            pathname="", lineno=0,
            msg="header dump: %s",
            args=("Authorization: Bearer secret_token_xyz",),
            exc_info=None,
        )
        f.filter(record)
        assert isinstance(record.args, tuple)
        assert "secret_token_xyz" not in record.args[0]
        assert "<redacted>" in record.args[0]

    def test_keyword_args_dict_redacted(self) -> None:
        """log.error('%(key)s', {'api_key': val}) must not emit val."""
        f = RedactingFilter()
        # LogRecord constructor chokes on a bare dict in Python ≥ 3.12
        # (tries dict[0] expecting a mapping-in-a-tuple pattern).
        # Set args after construction to simulate the real call-path.
        record = logging.LogRecord(
            name="test", level=logging.ERROR,
            pathname="", lineno=0,
            msg="gateway: %(info)s",
            args=(),
            exc_info=None,
        )
        record.args = {"info": "api_key=live_secret_12345"}
        f.filter(record)
        assert isinstance(record.args, dict)
        assert "live_secret_12345" not in record.args["info"]
        assert "<redacted>" in record.args["info"]

    def test_non_string_positional_args_pass_through(self) -> None:
        """Non-string args (int, dict) must not raise and must pass unchanged."""
        f = RedactingFilter()
        record = logging.LogRecord(
            name="test", level=logging.DEBUG,
            pathname="", lineno=0,
            msg="count: %d",
            args=(42,),
            exc_info=None,
        )
        result = f.filter(record)
        assert result is True
        assert record.args == (42,)


class TestRedactingFilterTraceback:
    """Law 2 face 2 — secrets embedded in exception messages must be redacted.

    Secrets leak through tracebacks more often than through intentional log
    messages. Example:
        raise ValueError(f"ERP rejected {order_id} with token={auth_token}")
    The traceback includes the exception message verbatim.
    """

    def test_exception_message_with_token_is_redacted(self) -> None:
        """Traceback containing 'token=<secret>' must not reach log output."""
        try:
            raise ValueError("ERP call failed: token=sk_live_verysecret")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        f = RedactingFilter()
        record = logging.LogRecord(
            name="test", level=logging.ERROR,
            pathname="", lineno=0,
            msg="ERP error",
            args=(),
            exc_info=exc_info,
        )
        f.filter(record)

        # Filter should freeze the traceback as exc_text (redacted)
        # and clear exc_info to prevent re-formatting.
        assert record.exc_info is None, "exc_info must be cleared after redaction"
        assert record.exc_text is not None, "exc_text must hold redacted traceback"
        assert "verysecret" not in record.exc_text
        assert "<redacted>" in record.exc_text

    def test_exception_without_sensitive_data_preserves_exc_info(self) -> None:
        """If the traceback has no sensitive data, exc_info is left intact."""
        try:
            raise RuntimeError("order not found: ord_abc123")
        except RuntimeError:
            import sys
            exc_info = sys.exc_info()

        f = RedactingFilter()
        record = logging.LogRecord(
            name="test", level=logging.ERROR,
            pathname="", lineno=0,
            msg="lookup failed",
            args=(),
            exc_info=exc_info,
        )
        f.filter(record)

        # No sensitive data → exc_info is untouched (Formatter re-formats normally)
        assert record.exc_info is not None, "exc_info must be preserved when no secrets found"

    def test_x_admin_secret_in_traceback_redacted(self) -> None:
        """X-Admin-Secret appearing in an exception message must be redacted."""
        secret = "admin_secret_9876"
        try:
            raise PermissionError(f"Auth failed: X-Admin-Secret={secret}")
        except PermissionError:
            import sys
            exc_info = sys.exc_info()

        f = RedactingFilter()
        record = logging.LogRecord(
            name="test", level=logging.ERROR,
            pathname="", lineno=0,
            msg="admin auth failure",
            args=(),
            exc_info=exc_info,
        )
        f.filter(record)

        assert record.exc_text is not None
        assert secret not in record.exc_text
        assert "<redacted>" in record.exc_text


class TestFilterInstallation:
    def test_filter_can_be_added_to_any_handler(self) -> None:
        """RedactingFilter.filter() returns True so the record is always emitted."""
        f = RedactingFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0,
            msg="secret_key=abc123",
            args=(), exc_info=None,
        )
        result = f.filter(record)
        assert result is True
        assert "abc123" not in record.msg

    def test_filter_is_idempotent(self) -> None:
        """Applying the filter twice does not double-redact or corrupt the message."""
        f = RedactingFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0,
            msg="token=mysecrettoken",
            args=(), exc_info=None,
        )
        f.filter(record)
        msg_after_first = record.msg
        f.filter(record)
        assert record.msg == msg_after_first
