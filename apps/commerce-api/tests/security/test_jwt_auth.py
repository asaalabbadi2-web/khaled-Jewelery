"""JWT auth unit tests — Law 1 + Law 4 runtime enforcement (ADR-017, ADR-018).

Tests the auth.py layer directly without touching FastAPI routing.
Covers: valid tokens, expired tokens, wrong secret, missing claims, no token.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from yasargold_commerce.auth import (
    TokenClaims,
    _decode,
    get_customer_ref,
    require_admin,
)

_SECRET = "test_jwt_secret_sprint10"
_ALGORITHM = "HS256"


def _token(
    sub: str = "+966500000001",
    scope: str = "customer",
    secret: str = _SECRET,
    exp_delta: timedelta = timedelta(hours=1),
) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "scope": scope, "iat": now, "exp": now + exp_delta}
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ---------------------------------------------------------------------------
# _decode
# ---------------------------------------------------------------------------

class TestDecode:
    def setup_method(self) -> None:
        os.environ["JWT_SECRET_KEY"] = _SECRET

    def teardown_method(self) -> None:
        os.environ.pop("JWT_SECRET_KEY", None)

    def test_valid_customer_token_decoded(self) -> None:
        claims = _decode(_token())
        assert claims.sub == "+966500000001"
        assert claims.scope == "customer"

    def test_valid_admin_token_decoded(self) -> None:
        claims = _decode(_token(scope="admin"))
        assert claims.scope == "admin"

    def test_expired_token_raises_401(self) -> None:
        token = _token(exp_delta=timedelta(seconds=-1))
        with pytest.raises(HTTPException) as exc:
            _decode(token)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail.lower()

    def test_wrong_secret_raises_401(self) -> None:
        token = _token(secret="wrong_secret")
        with pytest.raises(HTTPException) as exc:
            _decode(token)
        assert exc.value.status_code == 401

    def test_missing_sub_raises_401(self) -> None:
        now = datetime.now(timezone.utc)
        payload = {"scope": "customer", "exp": now + timedelta(hours=1)}
        token = jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)
        with pytest.raises(HTTPException) as exc:
            _decode(token)
        assert exc.value.status_code == 401
        assert "sub" in exc.value.detail

    def test_missing_scope_raises_401(self) -> None:
        now = datetime.now(timezone.utc)
        payload = {"sub": "+966500000001", "exp": now + timedelta(hours=1)}
        token = jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)
        with pytest.raises(HTTPException) as exc:
            _decode(token)
        assert exc.value.status_code == 401

    def test_jwt_secret_not_configured_raises_503(self) -> None:
        os.environ.pop("JWT_SECRET_KEY", None)
        with pytest.raises(HTTPException) as exc:
            _decode(_token())
        assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------

class TestRequireAdmin:
    def setup_method(self) -> None:
        os.environ["JWT_SECRET_KEY"] = _SECRET

    def teardown_method(self) -> None:
        os.environ.pop("JWT_SECRET_KEY", None)

    def test_admin_token_passes(self) -> None:
        require_admin(credentials=_credentials(_token(scope="admin")))

    def test_customer_token_raises_403(self) -> None:
        with pytest.raises(HTTPException) as exc:
            require_admin(credentials=_credentials(_token(scope="customer")))
        assert exc.value.status_code == 403
        assert "admin" in exc.value.detail.lower()

    def test_no_credentials_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc:
            require_admin(credentials=None)
        assert exc.value.status_code == 401
