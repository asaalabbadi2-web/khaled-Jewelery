-- SafeBox vs GL reconciliation (cash)
-- Returns safe boxes where derived SafeBox ledger differs from GL.
-- Threshold 0.009 to ignore tiny float noise.

WITH gl AS (
  SELECT
    sb.id AS safe_box_id,
    SUM((COALESCE(jel.cash_debit,0) - COALESCE(jel.cash_credit,0)))::numeric(18,2) AS gl_net
  FROM journal_entry_line jel
  JOIN journal_entry je ON je.id = jel.journal_entry_id
  JOIN safe_box sb ON sb.account_id = jel.account_id
  WHERE COALESCE(jel.is_deleted,false)=false
    AND COALESCE(je.is_deleted,false)=false
    AND COALESCE(je.is_draft,false)=false
    AND COALESCE(je.is_posted,true)=true
  GROUP BY sb.id
),
 sb AS (
  SELECT
    safe_box_id,
    SUM(
      CASE
        WHEN direction='in' THEN COALESCE(amount_cash,0)
        ELSE -COALESCE(amount_cash,0)
      END
    )::numeric(18,2) AS sb_net
  FROM safe_box_transaction
  GROUP BY safe_box_id
)
SELECT *
FROM (
  SELECT
    COALESCE(gl.safe_box_id, sb.safe_box_id) AS safe_box_id,
    COALESCE(sb.sb_net,0) AS sb_net,
    COALESCE(gl.gl_net,0) AS gl_net,
    (COALESCE(gl.gl_net,0) - COALESCE(sb.sb_net,0)) AS diff
  FROM gl
  FULL OUTER JOIN sb ON sb.safe_box_id = gl.safe_box_id
) t
WHERE abs(diff) > 0.009
ORDER BY abs(diff) DESC;
