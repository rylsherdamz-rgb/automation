Set-Location -Path $PSScriptRoot
$ErrorActionPreference = "Continue"
if (-not (Test-Path "logs")) { New-Item -ItemType Directory -Path "logs" | Out-Null }

# Once-per-day guard: skip if a successful upload already happened today.
$marker = Join-Path $PSScriptRoot "last_upload_date.txt"
$today = Get-Date -Format "yyyy-MM-dd"
if ((Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $today)) {
    exit 0
}

$log = Join-Path $PSScriptRoot ("logs\run_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

# Retry up to 3x (handles network / antivirus TLS not being ready right after login).
# -u keeps Python output unbuffered so the log captures progress even on a crash.
$code = 1
for ($i = 1; $i -le 3 -and $code -ne 0; $i++) {
    "==== attempt $i at $(Get-Date -Format HH:mm:ss) ====" | Out-File -FilePath $log -Append -Encoding utf8
    & "$PSScriptRoot\.venv\Scripts\python.exe" -u -m src.pipeline >> $log 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0 -and $i -lt 3) { Start-Sleep -Seconds 60 }
}

# Mark today done ONLY on success, so a failed run retries on the next login.
if ($code -eq 0) { Set-Content -Path $marker -Value $today -NoNewline -Encoding utf8 }
exit $code
