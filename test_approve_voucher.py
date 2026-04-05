import sys
sys.path.insert(0, '/Users/salehalabbadi/yasargold/backend')

from app import app

with app.app_context():
    from models import db, Supplier, Voucher, VoucherAccountLine, Account, SafeBox
    from datetime import date

    s = Supplier.query.filter(Supplier.account_id.isnot(None)).first()
    supplier_acc = Account.query.get(s.account_id)

    # Find a gold safe box (karat not null) or any safe
    sb_gold = SafeBox.query.filter(SafeBox.karat.isnot(None)).first()
    if not sb_gold:
        sb_gold = SafeBox.query.filter(SafeBox.safe_type == 'gold').first()
    if not sb_gold:
        sb_gold = SafeBox.query.first()

    print(f"Supplier: {s.id} {s.name}, account: {supplier_acc.id} {supplier_acc.account_number}")
    print(f"Gold SafeBox: {sb_gold.id} {sb_gold.name}, account_id: {sb_gold.account_id}, karat: {sb_gold.karat}, type: {sb_gold.safe_type}")

    # Check if supplier has a memo account
    memo_acc = None
    if supplier_acc.memo_account_id:
        memo_acc = Account.query.get(supplier_acc.memo_account_id)
        print(f"Memo account: {memo_acc.id} {memo_acc.account_number} {memo_acc.name}")

    # Create a draft GOLD payment voucher
    v = Voucher(
        voucher_number='TEST-PV-GOLD-002',
        voucher_type='payment',
        party_type='supplier',
        supplier_id=s.id,
        description='اختبار سند صرف ذهب للمورد',
        date=date.today(),
        status='draft',
        amount_cash=0.0,
        amount_gold=10.0,
        created_by='test',
    )
    db.session.add(v)
    db.session.flush()

    # Debit: supplier account (مدين المورد)
    l1 = VoucherAccountLine(
        voucher_id=v.id,
        account_id=supplier_acc.id,
        line_type='debit',
        amount_type='gold',
        amount=10.0,
        karat=21,
        description='دفعة ذهب للمورد',
    )
    # Credit: gold safe account (دائن الخزنة الذهبية)
    l2 = VoucherAccountLine(
        voucher_id=v.id,
        account_id=sb_gold.account_id,
        line_type='credit',
        amount_type='gold',
        amount=10.0,
        karat=21,
        description='من الخزنة الذهبية',
    )
    db.session.add_all([l1, l2])
    db.session.commit()
    print(f"Gold Voucher created: id={v.id}")

    from routes import create_journal_entry_from_voucher
    try:
        je = create_journal_entry_from_voucher(v)
        if je:
            db.session.commit()
            print(f"SUCCESS - JE: {je.id} {je.entry_number}")
            # print lines
            for line in je.lines:
                print(f"  Line {line.id}: acct={line.account_id} supplier={line.supplier_id} cd={line.cash_debit} cc={line.cash_credit} d21={line.debit_21k} c21={line.credit_21k}")
        else:
            print("FAILED - returned None")
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.session.rollback()

    # Cleanup
    try:
        db.session.delete(v)
        db.session.commit()
    except Exception:
        db.session.rollback()
    print("Done")

