#!/usr/bin/env python3
"""
Test script for new auth endpoints:
- login → refresh token
- logout → blacklist
- refresh → token rotation
- 2FA flow (if enabled)
"""
import requests
import json

BASE_URL = 'http://127.0.0.1:8001/api'

def test_login():
    """Test login and receive access + refresh token."""
    print("\n=== TEST: Login ===")
    response = requests.post(f'{BASE_URL}/auth/login', json={
        'username': 'sales2',
        'password': '123456',
        'remember_me': False,
    })
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Success: {data.get('success')}")
    
    if data.get('success'):
        access_token = data.get('token')
        refresh_token = data.get('refresh_token')
        print(f"Access Token: {access_token[:50]}...")
        print(f"Refresh Token: {refresh_token[:50] if refresh_token else 'N/A'}...")
        return access_token, refresh_token
    else:
        print(f"Error: {data.get('message')}")
        return None, None


def test_refresh(refresh_token):
    """Test refresh endpoint (token rotation)."""
    print("\n=== TEST: Refresh Token ===")
    if not refresh_token:
        print("No refresh token to test.")
        return None, None
    
    response = requests.post(f'{BASE_URL}/auth/refresh', json={
        'refresh_token': refresh_token,
    })
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Success: {data.get('success')}")
    
    if data.get('success'):
        new_access = data.get('token')
        new_refresh = data.get('refresh_token')
        print(f"New Access Token: {new_access[:50] if new_access else 'N/A'}...")
        print(f"New Refresh Token: {new_refresh[:50] if new_refresh else 'N/A'}...")
        return new_access, new_refresh
    else:
        print(f"Error: {data.get('message')}")
        return None, None


def test_sessions(access_token):
    """List active sessions."""
    print("\n=== TEST: List Sessions ===")
    if not access_token:
        print("No access token.")
        return
    
    response = requests.get(f'{BASE_URL}/auth/sessions', headers={
        'Authorization': f'Bearer {access_token}',
    })
    print(f"Status: {response.status_code}")
    data = response.json()

    # New backend returns a JSON array; older backend returned {success, sessions}
    if isinstance(data, list):
        sessions = data
        print("Success: True")
        print(f"Sessions: {len(sessions)}")
        for s in sessions[:3]:
            print(
                f"  - Session {s.get('id')}: active={s.get('is_active')}, IP={s.get('ip_address')}"
            )
        return

    print(f"Success: {data.get('success')}")
    if data.get('success'):
        sessions = data.get('sessions', [])
        print(f"Sessions: {len(sessions)}")
        for s in sessions[:3]:
            print(f"  - Session {s['id']}: revoked={s['is_revoked']}, IP={s['ip_address']}")


def test_logout(access_token, refresh_token):
    """Test logout (blacklist access + revoke refresh)."""
    print("\n=== TEST: Logout ===")
    if not access_token:
        print("No access token.")
        return
    
    response = requests.post(f'{BASE_URL}/auth/logout', 
        headers={'Authorization': f'Bearer {access_token}'},
        json={'refresh_token': refresh_token} if refresh_token else {}
    )
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Success: {data.get('success')}")
    print(f"Message: {data.get('message')}")


def test_reuse_blacklisted(access_token):
    """Try to use a blacklisted token (should fail)."""
    print("\n=== TEST: Reuse Blacklisted Token ===")
    if not access_token:
        print("No access token.")
        return
    
    # Try to access a protected endpoint
    response = requests.get(f'{BASE_URL}/auth/sessions', headers={
        'Authorization': f'Bearer {access_token}',
    })
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Success: {data.get('success')}")
    print(f"Message: {data.get('message', 'N/A')}")


if __name__ == '__main__':
    print("=" * 60)
    print("AUTH FLOW TEST SCRIPT")
    print("=" * 60)
    
    # 1. Login
    access1, refresh1 = test_login()
    
    if not access1:
        print("\n❌ Login failed. Stopping tests.")
        exit(1)
    
    # 2. List sessions
    test_sessions(access1)
    
    # 3. Refresh token
    access2, refresh2 = test_refresh(refresh1)
    
    # 4. Logout (blacklist + revoke)
    test_logout(access2 if access2 else access1, refresh2 if refresh2 else refresh1)
    
    # 5. Try to reuse blacklisted token
    test_reuse_blacklisted(access2 if access2 else access1)
    
    print("\n" + "=" * 60)
    print("✅ Test script completed.")
    print("=" * 60)
