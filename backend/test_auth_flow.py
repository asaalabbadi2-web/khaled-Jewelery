#!/usr/bin/env python3
"""Manual auth flow script (NOT a pytest test).

This file is intentionally named with the historical `test_*.py` prefix.
To avoid pytest noise/breakage, functions are *not* named `test_*`.
"""

import requests
from typing import Optional

BASE_URL = 'http://127.0.0.1:8001/api'


def run_login(username: str, password: str):
    print("\n=== Login ===")
    response = requests.post(
        f'{BASE_URL}/auth/login',
        json={'username': username, 'password': password, 'remember_me': False},
        timeout=10,
    )
    print(f"Status: {response.status_code}")
    data = response.json()
    if data.get('success'):
        access_token = data.get('token')
        refresh_token = data.get('refresh_token')
        print(f"Access Token: {access_token[:50]}...")
        print(f"Refresh Token: {refresh_token[:50] if refresh_token else 'N/A'}...")
        return access_token, refresh_token
    print(f"Error: {data.get('message')}")
    return None, None


def run_refresh(refresh_token: str):
    print("\n=== Refresh Token ===")
    response = requests.post(
        f'{BASE_URL}/auth/refresh',
        json={'refresh_token': refresh_token},
        timeout=10,
    )
    print(f"Status: {response.status_code}")
    data = response.json()
    if data.get('success'):
        return data.get('token'), data.get('refresh_token')
    print(f"Error: {data.get('message')}")
    return None, None


def run_sessions(access_token: str):
    print("\n=== List Sessions ===")
    response = requests.get(
        f'{BASE_URL}/auth/sessions',
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=10,
    )
    print(f"Status: {response.status_code}")
    data = response.json()
    print(data if isinstance(data, list) else {k: data.get(k) for k in ('success', 'message', 'error')})


def run_logout(access_token: str, refresh_token: Optional[str]):
    print("\n=== Logout ===")
    response = requests.post(
        f'{BASE_URL}/auth/logout',
        headers={'Authorization': f'Bearer {access_token}'},
        json={'refresh_token': refresh_token} if refresh_token else {},
        timeout=10,
    )
    print(f"Status: {response.status_code}")
    print(response.json())


def run_reuse_blacklisted(access_token: str):
    print("\n=== Reuse Blacklisted Token ===")
    response = requests.get(
        f'{BASE_URL}/auth/sessions',
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=10,
    )
    print(f"Status: {response.status_code}")
    print(response.json())


def main() -> int:
    access1, refresh1 = run_login('admin', 'admin123')
    if not access1:
        print("\n❌ Login failed")
        return 1

    run_sessions(access1)

    access2, refresh2 = (None, None)
    if refresh1:
        access2, refresh2 = run_refresh(refresh1)

    run_logout(access2 or access1, refresh2 or refresh1)
    run_reuse_blacklisted(access2 or access1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
