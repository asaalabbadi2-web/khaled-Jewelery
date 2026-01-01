#requires -Version 5.1
<
PostgreSQL backup for YasarGold (Windows).

Examples:
  pwsh -File .\backend\backup_postgres.ps1 -DatabaseUrl "postgresql://user:pass@host:5432/db"
  pwsh -File .\backend\backup_postgres.ps1 -DatabaseUrl "..." -BackupDir "C:\\yasargold\\backups\\postgres" -RetentionDays 14

Notes:
- Requires pg_dump in PATH (PostgreSQL client tools installed).
- Prefer .pgpass / secret manager instead of embedding password.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [string]$DatabaseUrl,

  [string]$BackupDir = $(Join-Path (Split-Path -Parent $PSCommandPath) "..\backups\postgres"),

  [int]$RetentionDays = 14
)

if ($DatabaseUrl -notmatch '^postgres(ql)?://') {
  throw "DatabaseUrl does not look like PostgreSQL: $DatabaseUrl"
}

$pgDump = (Get-Command pg_dump -ErrorAction SilentlyContinue)
if (-not $pgDump) {
  throw "pg_dump not found in PATH. Install PostgreSQL client tools." 
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$ts = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$outFile = Join-Path $BackupDir "yasargold_pg_${ts}.dump"

& $pgDump.Source --format=custom --no-owner --no-acl --dbname $DatabaseUrl --file $outFile
if ($LASTEXITCODE -ne 0) {
  throw "pg_dump failed with exit code $LASTEXITCODE"
}

Write-Host "OK: created backup: $outFile"

if ($RetentionDays -gt 0) {
  $cutoff = (Get-Date).ToUniversalTime().AddDays(-$RetentionDays)
  Get-ChildItem -Path $BackupDir -Filter 'yasargold_pg_*.dump' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTimeUtc -lt $cutoff } |
    Remove-Item -Force -ErrorAction SilentlyContinue
}
