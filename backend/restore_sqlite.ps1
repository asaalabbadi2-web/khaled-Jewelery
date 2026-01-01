#requires -Version 5.1
<
SQLite restore for YasarGold (Windows).

Examples:
  pwsh -File .\backend\restore_sqlite.ps1 -BackupFile "C:\\...\\yasargold_sqlite_....db" -ConfirmRestore YES

Notes:
- Saves a safety copy of the current DB if present.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [string]$BackupFile,

  [ValidateSet('YES')]
  [string]$ConfirmRestore,

  [string]$SqliteDbPath = $(Join-Path (Split-Path -Parent $PSCommandPath) 'app.db')
)

if (-not (Test-Path -LiteralPath $BackupFile)) {
  throw "BackupFile not found: $BackupFile"
}

if (Test-Path -LiteralPath $SqliteDbPath) {
  $ts = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  $snapshot = "$SqliteDbPath.before_restore_$ts"
  Copy-Item -LiteralPath $SqliteDbPath -Destination $snapshot -Force
  Write-Host "Saved current DB snapshot: $snapshot"
}

Copy-Item -LiteralPath $BackupFile -Destination $SqliteDbPath -Force
Write-Host "OK: restored SQLite DB to: $SqliteDbPath"
Write-Host "Next: restart backend server"
