"""Root conftest — shared fixtures applied to the entire test suite.

Fixtures here run for every test file under tests/.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the shared FakeRedis between tests to prevent counter bleed-over.

    The RateLimitMiddleware in main.py holds a reference to a module-level
    FakeRedis instance (_RATE_REDIS). Without resetting it, tests that share
    the same rate-limited endpoint accumulate hits across the session and
    eventually receive 429 responses even though they should pass.
    """
    from yasargold_commerce.main import _RATE_REDIS
    from yasargold_commerce.rate_limiter import FakeRedis
    if isinstance(_RATE_REDIS, FakeRedis):
        _RATE_REDIS.reset()
    yield
    if isinstance(_RATE_REDIS, FakeRedis):
        _RATE_REDIS.reset()
