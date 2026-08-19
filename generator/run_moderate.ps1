Set-Location -Path $PSScriptRoot
$ErrorActionPreference = "Continue"
if (-not (Test-Path "logs")) { New-Item -ItemType Directory -Path "logs" | Out-Null }
$log = Join-Path $PSScriptRoot ("logs\mod_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
& "$PSScriptRoot\.venv\Scripts\python.exe" -u -m src.moderate > $log 2>&1
exit $LASTEXITCODE
