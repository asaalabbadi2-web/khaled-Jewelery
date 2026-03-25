param(
  [string]$DbContainer = "yasargold-db",
  [string]$DbUser = "yasargold",
  [string]$DbName = "yasargold_db",
  [int]$SafeId = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-PsqlQuery {
  param([string]$Sql)
  docker exec -i $DbContainer psql -U $DbUser -d $DbName -c $Sql
}

function Get-SafeBoxGlDiff {
  $SQL = @"
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
"@

  Invoke-PsqlQuery -Sql $SQL
}

function Get-SafeBoxKeyedDiff {
  param([int]$SafeId)

  if ($SafeId -le 0) {
    throw "SafeId must be provided (e.g. -SafeId 38)."
  }

  $SQL = @"
WITH safe AS (
  SELECT id, account_id FROM safe_box WHERE id = $SafeId
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
  WHERE safe_box_id = $SafeId
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
"@

  Invoke-PsqlQuery -Sql $SQL
}

Write-Host "== SafeBox vs GL diff ==" -ForegroundColor Cyan
Get-SafeBoxGlDiff

if ($SafeId -gt 0) {
  Write-Host "\n== Keyed diff for SafeId=$SafeId ==" -ForegroundColor Cyan
  Get-SafeBoxKeyedDiff -SafeId $SafeId
}
