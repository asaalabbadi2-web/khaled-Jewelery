-- Keyed SafeBox vs GL reconciliation for a single SafeBox.
-- NOTE: Replace SAFE_ID_HERE with the desired safe_box.id before running.

WITH safe AS (
  SELECT id, account_id FROM safe_box WHERE id = SAFE_ID_HERE
),
 gl_keyed AS (
  SELECT
    CASE
      WHEN lower(trim(coalesce(je.reference_type,''))) = '' THEN 'journal_entry'
      ELSE lower(trim(coalesce(je.reference_type,'')))
    END AS ref_type,
    CASE
      WHEN lower(trim(coalesce(je.reference_type,''))) = '' OR COALESCE(je.reference_id,0)=0 THEN je.id
      ELSE je.reference_id::int
    END AS ref_id,
    SUM((COALESCE(jel.cash_debit,0) - COALESCE(jel.cash_credit,0)))::numeric(18,2) AS gl_signed
  FROM journal_entry_line jel
  JOIN journal_entry je ON je.id = jel.journal_entry_id
  JOIN safe s ON s.account_id = jel.account_id
  WHERE COALESCE(jel.is_deleted,false)=false
    AND COALESCE(je.is_deleted,false)=false
    AND COALESCE(je.is_draft,false)=false
    AND COALESCE(je.is_posted,true)=true
  GROUP BY 1,2
),
 sb_keyed AS (
  SELECT
    CASE
      WHEN lower(trim(coalesce(ref_type,'')))='invoice_payment'
       AND COALESCE(invoice_payment_id,0) <> 0
       AND COALESCE(ref_id,0) <> 0
       AND ref_id <> invoice_payment_id
        THEN 'voucher'
      ELSE lower(trim(coalesce(ref_type,'')))
    END AS ref_type,
    ref_id::int AS ref_id,
    SUM(
      CASE
        WHEN direction='in' THEN COALESCE(amount_cash,0)
        ELSE -COALESCE(amount_cash,0)
      END
    )::numeric(18,2) AS sb_signed
  FROM safe_box_transaction
  WHERE safe_box_id = SAFE_ID_HERE
  GROUP BY 1,2
)
SELECT
  COALESCE(gl.ref_type, sb.ref_type) AS ref_type,
  COALESCE(gl.ref_id, sb.ref_id) AS ref_id,
  COALESCE(sb.sb_signed,0) AS sb_signed,
  COALESCE(gl.gl_signed,0) AS gl_signed,
  (COALESCE(sb.sb_signed,0) - COALESCE(gl.gl_signed,0)) AS diff
FROM sb_keyed sb
FULL OUTER JOIN gl_keyed gl
  ON gl.ref_type = sb.ref_type AND gl.ref_id = sb.ref_id
WHERE abs(COALESCE(sb.sb_signed,0) - COALESCE(gl.gl_signed,0)) > 0.009
ORDER BY abs(COALESCE(sb.sb_signed,0) - COALESCE(gl.gl_signed,0)) DESC
LIMIT 50;
