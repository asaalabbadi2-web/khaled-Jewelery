"""JWT authentication layer — Law 1 + Law 4 runtime enforcement (ADR-017, ADR-018).

FastAPI dependencies exported from this module:

    get_customer_ref(credentials) -> str
        Require a valid JWT. Returns JWT `sub` as the customer identity
        (customer_ref) for BOLA ownership checks. Raises 401 if missing or
        invalid; 503 if JWT_SECRET_KEY is not configured.

    require_admin(credentials) -> None
        Require a valid JWT with scope="admin". Raises 401 if missing or
        invalid; 403 if scope != "admin"; 503 if not configured.

SEC-001 withdrawal: require_admin_secret (X-Admin-Secret) is withdrawn
once require_admin is wired on every admin-scoped endpoint AND the test
in test_admin_scope_enforcement.py passes. See ADR-017 §Consequences.

JWT claims required:
    sub   — customer identity (phone number, customer ID, etc.)
    scope — "customer" | "admin"
    exp   — expiry (validated by PyJWT automatically)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import jwt as _jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_ALGORITHM = "HS256"
_BEARER = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class TokenClaims:
    sub: str    # customer identity
    scope: str  # "customer" | "admin"


class _JWTNotConfigured(Exception):
    pass


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        raise _JWTNotConfigured
    return secret


def _decode(token: str) -> TokenClaims:
    try:
        secret = _secret()
    except _JWTNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not configured — set JWT_SECRET_KEY",
        )

    try:
        payload = _jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    sub = payload.get("sub")
    scope = payload.get("scope")
    if not sub or not scope:
        raise HTTPException(
            status_code=401,
            detail="Token missing required claims (sub, scope)",
        )

    return TokenClaims(sub=str(sub), scope=str(scope))


def _get_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER),
) -> TokenClaims:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode(credentials.credentials)


def get_customer_ref(
    claims: TokenClaims = Depends(_get_claims),
) -> str:
    """Return the JWT `sub` claim as the customer identity.

    Used as `customer_ref` in domain BOLA calls:
        order = order_service.find_order_for_customer(order_id, customer_ref, uow)

    Raises 401 if no valid Bearer token is present.
    """
    return claims.sub


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER),
) -> None:
    """Require a valid JWT with scope="admin".

    Replaces require_admin_secret (X-Admin-Secret) under SEC-001 withdrawal
    condition. See ADR-017 §SEC-001 withdrawal condition.

    Returns None on success (used as Depends(_) in router signatures).
    Raises:
        401 — missing or invalid token
        403 — valid token but scope != "admin"
        503 — JWT_SECRET_KEY not configured
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = _decode(credentials.credentials)
    if claims.scope != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin scope required",
        )
