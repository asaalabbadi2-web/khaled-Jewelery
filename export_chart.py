#!/usr/bin/env python3
"""Export current chart of accounts"""

import sys
import os

# Add backend to path
backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
sys.path.insert(0, backend_dir)
os.chdir(backend_dir)

from app import app, db
from models import Account
import json
from datetime import datetime

with app.app_context():
    accounts = Account.query.order_by(Account.account_number).all()
    
    # Export current chart
    accounts_data = []
    for acc in accounts:
        accounts_data.append({
            "account_number": acc.account_number,
            "name": acc.name,
            "type": acc.type,
            "transaction_type": acc.transaction_type,
            "tracks_weight": acc.tracks_weight or False,
            "parent_account_number": acc.parent.account_number if acc.parent else None,
            "is_active": getattr(acc, 'is_active', True)
        })
    
    # Save as backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"../exports/accounts_backup_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump({
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "count": len(accounts_data),
            "accounts": accounts_data
        }, f, ensure_ascii=False, indent=2)
    
    print(f"✅ تم حفظ آخر شجرة حسابات: {filename}")
    print(f"📊 عدد الحسابات: {len(accounts_data)}")
