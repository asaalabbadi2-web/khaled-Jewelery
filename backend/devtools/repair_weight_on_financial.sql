-- ============================================================
-- إصلاح قيود الوزن المكتوبة على الحسابات المالية
-- ============================================================
-- المشكلة: debit_Xk / credit_Xk كُتبت على حسابات ماليّة (1300، 1310، 1200...)
--           بدلاً من حسابات الوزن المذكرة (7130000، 7130001، 71200...).
--           نتيجة: debit_weight / credit_weight تبقى صفراً لأن create_dual_journal_entry
--                  تضبط تلك العمودين فقط للحسابات التي تبدأ بـ 7.
-- الحل: نُبدّل account_id بـ memo_account_id، ونُعيد حساب debit_weight/credit_weight.
-- ============================================================
-- معادلة الوزن الموحّد (عيار 21 أساس):
--   debit_weight  = d18*18/21 + d21*1 + d22*22/21 + d24*24/21
--   credit_weight = c18*18/21 + c21*1 + c22*22/21 + c24*24/21
-- ============================================================
-- ملاحظة: هذا السكريبت لا يُنشئ سطوراً جديدة — فقط يُصحّح السطور الموجودة.
--         للـ PostgreSQL استبدل COALESCE(is_deleted,0) بـ COALESCE(is_deleted,false).
-- ============================================================

BEGIN;

UPDATE journal_entry_line
SET
    account_id     = (SELECT memo_account_id FROM account WHERE id = journal_entry_line.account_id),
    debit_weight   = ROUND(
                       COALESCE(debit_18k,  0) * 18.0 / 21
                     + COALESCE(debit_21k,  0) * 1.0
                     + COALESCE(debit_22k,  0) * 22.0 / 21
                     + COALESCE(debit_24k,  0) * 24.0 / 21
                     , 6),
    credit_weight  = ROUND(
                       COALESCE(credit_18k, 0) * 18.0 / 21
                     + COALESCE(credit_21k, 0) * 1.0
                     + COALESCE(credit_22k, 0) * 22.0 / 21
                     + COALESCE(credit_24k, 0) * 24.0 / 21
                     , 6)
WHERE
    COALESCE(is_deleted, 0) = 0
    AND (
        debit_18k  > 0 OR credit_18k  > 0 OR
        debit_21k  > 0 OR credit_21k  > 0 OR
        debit_22k  > 0 OR credit_22k  > 0 OR
        debit_24k  > 0 OR credit_24k  > 0
    )
    AND account_id IN (
        SELECT id FROM account
        WHERE account_number NOT LIKE '7%'
          AND memo_account_id IS NOT NULL
    );

-- Verify: should return 0 after repair
SELECT COUNT(*) AS remaining_bad_lines
FROM journal_entry_line jel
JOIN account a ON a.id = jel.account_id
WHERE
    (jel.debit_21k > 0 OR jel.credit_21k > 0 OR
     jel.debit_18k > 0 OR jel.credit_18k > 0 OR
     jel.debit_22k > 0 OR jel.credit_22k > 0 OR
     jel.debit_24k > 0 OR jel.credit_24k > 0)
    AND a.account_number NOT LIKE '7%'
    AND COALESCE(jel.is_deleted, 0) = 0;

COMMIT;
