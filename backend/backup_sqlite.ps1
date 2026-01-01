#requires -Version 5.1
<
SQLite backup for YasarGold (Windows).
Creates a consistent backup using Python's sqlite3 backup API.

Examples:
  pwsh -File .\backend\backup_sqlite.ps1
  pwsh -File .\backend\backup_sqlite.ps1 -SqliteDbPath "C:\\path\\app.db" -BackupDir "C:\\yasargold\\backups\\sqlite" -RetentionDays 14
#>

[CmdletBinding()]
param(
  [string]$SqliteDbPath = $(Join-Path (Split-Path -Parent $PSCommandPath) 'app.db'),
  [string]$BackupDir = $(Join-Path (Split-Path -Parent $PSCommandPath) "..\backups\sqlite"),
  [int]$RetentionDays = 14
)

if (-not (Test-Path -LiteralPath $SqliteDbPath)) {
  throw "SQLite DB not found: $SqliteDbPath"
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$ts = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$outFile = Join-Path $BackupDir "yasargold_sqlite_${ts}.db"

$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue) }
if (-not $py) {
  throw "python/python3 not found in PATH (needed for sqlite3 backup API)."
}

$code = @"
import sqlite3
src = r'''$SqliteDbPath'''
dst = r'''$outFile'''
src_conn = sqlite3.connect(src)
dst_conn = sqlite3.connect(dst)
try:
    src_conn.backup(dst_conn)
finally:
    dst_conn.close()
    src_conn.close()
print(dst)
"@

& $py.Source -c $code | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "python sqlite backup failed with exit code $LASTEXITCODE"
}

Write-Host "OK: created backup: $outFile"

if ($RetentionDays -gt 0) {
  $cutoff = (Get-Date).ToUniversalTime().AddDays(-$RetentionDays)
  Get-ChildItem -Path $BackupDir -Filter 'yasargold_sqlite_*.db' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTimeUtc -lt $cutoff } |
    Remove-Item -Force -ErrorAction SilentlyContinue
}
