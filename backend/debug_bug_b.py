#!/usr/bin/env python3
import requests, json

r = requests.post('http://localhost:8001/api/auth/login', json={'username':'admin','password':'admin123'})
t = r.json()['token']
h = {'Authorization': 'Bearer '+t, 'Content-Type': 'application/json'}

r_s = requests.get('http://localhost:8001/api/suppliers', headers=h)
sups = r_s.json() if isinstance(r_s.json(), list) else r_s.json().get('suppliers', [])
r_o = requests.get('http://localhost:8001/api/offices', headers=h)
offices = r_o.json()
linked_sids = {o.get('supplier_id') for o in offices if o.get('supplier_id')}

print(f"Total suppliers: {len(sups)}, offices: {len(offices)}")
print(f"Linked supplier IDs: {sorted(linked_sids)}")

free = [(s['id'], s['name']) for s in sups if s.get('id') not in linked_sids]
print(f"Free suppliers: {free[:5]}")

# Test explicit link mode
if free:
    free_id = free[0][0]
    print(f"\nTest A: explicit supplier_link_mode=existing + supplier_id={free_id}")
    r1 = requests.post('http://localhost:8001/api/offices', headers=h, json={
        'name': f'_DEBUG A {free_id}',
        'supplier_id': free_id,
        'supplier_link_mode': 'existing',
    })
    print(f"  Status: {r1.status_code}  supplier_id: {r1.json().get('supplier_id')}  expected: {free_id}")

# Test with just supplier_id (auto-detect should work)
if len(free) >= 2:
    free_id2 = free[1][0]
    print(f"\nTest B: auto-detect, just supplier_id={free_id2}")
    r2 = requests.post('http://localhost:8001/api/offices', headers=h, json={
        'name': f'_DEBUG B {free_id2}',
        'supplier_id': free_id2,
    })
    print(f"  Status: {r2.status_code}  supplier_id: {r2.json().get('supplier_id')}  expected: {free_id2}")
    if not r2.ok:
        print(f"  Error: {r2.json()}")
