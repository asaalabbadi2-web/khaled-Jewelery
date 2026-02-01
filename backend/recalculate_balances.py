"""
أداة لإعادة حساب أرصدة الحسابات من القيود اليومية
This utility recalculates account balances from journal entries and vouchers
"""
from app import app
from models import db, Account, JournalEntry, JournalEntryLine, Voucher, VoucherAccountLine


def recalculate_account_balances(account_id=None, verbose=True):
    """
    إعادة حساب أرصدة الحسابات من القيود اليومية والسندات
    
    Args:
        account_id: رقم الحساب (None = كل الحسابات)
        verbose: طباعة التفاصيل
    """
    with app.app_context():
        # تحديد الحسابات المراد تحديثها
        if account_id:
            accounts = [Account.query.get(account_id)]
            if not accounts[0]:
                print(f"❌ الحساب {account_id} غير موجود")
                return
        else:
            accounts = Account.query.all()
        
        print(f"🔄 جاري إعادة حساب أرصدة {len(accounts)} حساب...")
        
        updated_count = 0
        for account in accounts:
            # إعادة تعيين الأرصدة إلى صفر
            old_balance_cash = account.balance_cash
            old_balance_18k = account.balance_18k
            old_balance_21k = account.balance_21k
            old_balance_22k = account.balance_22k
            old_balance_24k = account.balance_24k
            
            account.balance_cash = 0.0
            account.balance_18k = 0.0
            account.balance_21k = 0.0
            account.balance_22k = 0.0
            account.balance_24k = 0.0
            
            # حساب الرصيد من قيود اليومية
            journal_lines = (
                JournalEntryLine.query
                .join(JournalEntry)
                .filter(
                    JournalEntryLine.account_id == account.id,
                    JournalEntry.is_deleted == False,
                    JournalEntry.is_draft == False,
                    JournalEntryLine.is_deleted == False,
                )
                .all()
            )
            
            for line in journal_lines:
                # تحديث النقد
                account.balance_cash += (line.cash_debit or 0) - (line.cash_credit or 0)
                
                # تحديث الأوزان إذا كان الحساب يتتبع الوزن
                if account.tracks_weight:
                    account.balance_18k += (line.debit_18k or 0) - (line.credit_18k or 0)
                    account.balance_21k += (line.debit_21k or 0) - (line.credit_21k or 0)
                    account.balance_22k += (line.debit_22k or 0) - (line.credit_22k or 0)
                    account.balance_24k += (line.debit_24k or 0) - (line.credit_24k or 0)
            
            # حساب الرصيد من السندات
            voucher_lines = (
                VoucherAccountLine.query
                .join(Voucher)
                .filter(
                    VoucherAccountLine.account_id == account.id
                )
                .all()
            )
            
            for line in voucher_lines:
                if line.line_type == 'debit':
                    account.balance_cash += (line.amount or 0)
                else:
                    account.balance_cash -= (line.amount or 0)
            
            # التحقق من التغييرات
            has_changes = (
                abs(old_balance_cash - account.balance_cash) > 0.001 or
                abs(old_balance_18k - account.balance_18k) > 0.001 or
                abs(old_balance_21k - account.balance_21k) > 0.001 or
                abs(old_balance_22k - account.balance_22k) > 0.001 or
                abs(old_balance_24k - account.balance_24k) > 0.001
            )
            
            if has_changes:
                updated_count += 1
                if verbose:
                    print(f"✅ {account.account_number} - {account.name}")
                    if abs(old_balance_cash - account.balance_cash) > 0.001:
                        print(f"   نقد: {old_balance_cash:.2f} → {account.balance_cash:.2f}")
                    if account.tracks_weight:
                        if abs(old_balance_18k - account.balance_18k) > 0.001:
                            print(f"   18k: {old_balance_18k:.3f} → {account.balance_18k:.3f}")
                        if abs(old_balance_21k - account.balance_21k) > 0.001:
                            print(f"   21k: {old_balance_21k:.3f} → {account.balance_21k:.3f}")
                        if abs(old_balance_22k - account.balance_22k) > 0.001:
                            print(f"   22k: {old_balance_22k:.3f} → {account.balance_22k:.3f}")
                        if abs(old_balance_24k - account.balance_24k) > 0.001:
                            print(f"   24k: {old_balance_24k:.3f} → {account.balance_24k:.3f}")
        
        # حفظ التغييرات
        db.session.commit()
        print(f"\n✅ تم تحديث {updated_count} حساب بنجاح")
        
        return updated_count


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        account_id = int(sys.argv[1])
        recalculate_account_balances(account_id=account_id)
    else:
        recalculate_account_balances()
