#requires -Version 5.1
<
PostgreSQL restore for YasarGold (Windows).

Examples:
  pwsh -File .\backend\restore_postgres.ps1 -DatabaseUrl "postgresql://..." -BackupFile "C:\\...\\yasargold_pg_....dump" -ConfirmRestore YES

WARNING:
- This overwrites existing data (uses --clean --if-exists).
- Best practice: restore into a NEW database first, then switch.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [string]$DatabaseUrl,

  [Parameter(Mandatory=$true)]
  [string]$BackupFile,

  [ValidateSet('YES')]
  [string]$ConfirmRestore
)

if ($DatabaseUrl -notmatch '^postgres(ql)?://') {
  throw "DatabaseUrl does not look like PostgreSQL: $DatabaseUrl"
}

if (-not (Test-Path -LiteralPath $BackupFile)) {
  throw "BackupFile not found: $BackupFile"
}

$pgRestore = (Get-Command pg_restore -ErrorAction SilentlyContinue)
if (-not $pgRestore) {
  throw "pg_restore not found in PATH. Install PostgreSQL client tools." 
}

Write-Host "Restoring: $BackupFile"
& $pgRestore.Source --clean --if-exists --no-owner --no-acl --dbname $DatabaseUrl $BackupFile
if ($LASTEXITCODE -ne 0) {
  throw "pg_restore failed with exit code $LASTEXITCODE"
}

Write-Host "OK: restore completed. Run migrations next: alembic upgrade head"
