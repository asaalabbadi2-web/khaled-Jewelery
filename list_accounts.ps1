# list_accounts.ps1
# يعرض جميع الحسابات من قاعدة بيانات الإنتاج

@'
import sys
sys.path.insert(0, "backend")
from app import app
from models import db, Account

with app.app_context():
    accounts = Account.query.order_by(Account.code).all()
    print(f"\n{'id':>5}  {'code':<15}  {'name':<40}  type")
    print("─" * 80)
    for a in accounts:
        print(f"{a.id:>5}  {str(a.code):<15}  {str(a.name):<40}  {a.account_type}")
    print(f"\nإجمالي الحسابات: {len(accounts)}")
'@ | docker exec -i yasargold-backend python 2>&1 | Select-String -NotMatch "schema_guard|Auto-migration|Startup bootstrap|psycopg2|Background on this error|FullyQualified"
