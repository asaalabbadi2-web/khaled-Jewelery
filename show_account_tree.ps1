# show_account_tree.ps1
# يعرض شجرة الحسابات مرتبة لاختيار موضع حساب الفروقات التاريخية

@'
import sys
sys.path.insert(0, "backend")
from app import app
from models import db, Account

with app.app_context():
    accounts = Account.query.order_by(Account.code).all()

    # بناء index بالـ id
    by_id = {a.id: a for a in accounts}

    def indent(a, depth=0):
        prefix = "  " * depth + ("└─ " if depth > 0 else "")
        code = str(a.code) if a.code else "—"
        print(f"{a.id:>5}  {code:<12}  {prefix}{a.name}  [{a.account_type}]")

    # طباعة الحسابات الجذرية أولاً، ثم أبناؤها
    roots = [a for a in accounts if not a.parent_id]
    children = {}
    for a in accounts:
        if a.parent_id:
            children.setdefault(a.parent_id, []).append(a)

    def print_tree(a, depth=0):
        indent(a, depth)
        for child in sorted(children.get(a.id, []), key=lambda x: str(x.code)):
            print_tree(child, depth + 1)

    print(f"\n{'id':>5}  {'code':<12}  {'name / شجرة'}")
    print("─" * 70)
    for root in sorted(roots, key=lambda x: str(x.code)):
        print_tree(root)

    print(f"\nإجمالي: {len(accounts)} حساب")

    # طباعة الحسابات من نوع equity/liability/expense كمقترحات
    print("\n─── حسابات قد تناسب الفروقات التاريخية ──────────────────────")
    candidates = [a for a in accounts if a.account_type in ('equity', 'liability', 'expense', 'other')]
    for a in sorted(candidates, key=lambda x: str(x.code)):
        print(f"  {a.id:>5}  {str(a.code):<12}  {a.name}  [{a.account_type}]")
'@ | docker exec -i yasargold-backend python 2>&1 | Select-String -NotMatch "schema_guard|Auto-migration|Startup bootstrap|psycopg2|Background on this error|FullyQualified"
