"""Analyze production data: supplier accounts under wrong (raw-gold) group."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, Account, Supplier, JournalEntryLine

def digits(v):
    return ''.join(c for c in str(v or '') if c.isdigit())

with app.app_context():
    accs = Account.query.all()
    by_id = {a.id: a for a in accs}

    # Which account IDs are under raw-gold (22xx) vs manufactured-gold (21xx) groups
    raw_ids  = {a.id for a in accs if digits(a.account_number).startswith('22')}
    mfg_ids  = {a.id for a in accs if digits(a.account_number).startswith('21')}
    raw_w_ids = {a.id for a in accs if digits(a.account_number).startswith('722')}
    mfg_w_ids = {a.id for a in accs if digits(a.account_number).startswith('721')}

    suppliers = Supplier.query.all()
    print(f"Total suppliers: {len(suppliers)}")
    print()

    issues = []
    ok_count = 0
    for s in suppliers:
        fin = by_id.get(s.account_id) if s.account_id else None
        memo_id = getattr(fin, 'memo_account_id', None) if fin else None
        memo = by_id.get(memo_id) if memo_id else None
        memo_parent = by_id.get(memo.parent_id) if memo and memo.parent_id else None

        fin_under_raw  = bool(fin and fin.parent_id in raw_ids)
        fin_under_mfg  = bool(fin and fin.parent_id in mfg_ids)
        memo_under_raw = bool(memo and memo.parent_id in raw_w_ids)

        if fin_under_raw or memo_under_raw:
            fin_lines  = JournalEntryLine.query.filter_by(account_id=s.account_id).count() if s.account_id else 0
            memo_lines = JournalEntryLine.query.filter_by(account_id=memo_id).count() if memo_id else 0
            parent_num = digits(getattr(by_id.get(fin.parent_id), 'account_number', '?')) if fin else '?'
            issues.append({
                's_id': s.id, 'name': s.name,
                'fin_id': s.account_id, 'fin_num': getattr(fin, 'account_number', None),
                'fin_parent_num': parent_num,
                'fin_under_raw': fin_under_raw,
                'fin_lines': fin_lines,
                'memo_id': memo_id,
                'memo_num': getattr(memo, 'account_number', None),
                'memo_parent_num': digits(getattr(memo_parent, 'account_number', '?')) if memo_parent else '?',
                'memo_under_raw': memo_under_raw,
                'memo_lines': memo_lines,
            })
        elif fin_under_mfg:
            ok_count += 1

    print(f"Suppliers with accounts CORRECTLY under 21xx (manufactured gold): {ok_count}")
    print(f"Suppliers with accounts WRONGLY under 22xx (raw gold): {len(issues)}")
    print()

    for i in issues:
        status = "FIN+MEMO BAD" if (i['fin_under_raw'] and i['memo_under_raw']) else ("FIN BAD" if i['fin_under_raw'] else "MEMO BAD")
        print(f"  sup {i['s_id']:3} | {status:12} | {i['name'][:32]:32} | "
              f"fin={i['fin_num']}(parent:{i['fin_parent_num']},lines={i['fin_lines']}) "
              f"memo={i['memo_num']}(parent:{i['memo_parent_num']},lines={i['memo_lines']})")

    print()
    total_fin_lines  = sum(i['fin_lines']  for i in issues if i['fin_under_raw'])
    total_memo_lines = sum(i['memo_lines'] for i in issues if i['memo_under_raw'])
    print(f"Total journal lines on wrong financial accounts: {total_fin_lines}")
    print(f"Total journal lines on wrong weight/memo accounts: {total_memo_lines}")
