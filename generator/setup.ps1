$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
  Write-Host "Creating virtualenv..."
  py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created .env -- edit it and add your API keys."
}

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "output" | Out-Null

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Warning "ffmpeg not found on PATH. Install it: winget install Gyan.FFmpeg"
}

if (-not (Test-Path "client_secret.json")) {
  Write-Warning "client_secret.json missing. Create OAuth credentials in Google Cloud Console -> YouTube Data API v3, download as client_secret.json into this folder."
}

Write-Host ""
Write-Host "Setup complete. Next steps:"
Write-Host "  1. Edit .env with your API keys"
Write-Host "  2. Put client_secret.json in this folder (OAuth desktop credentials)"
Write-Host "  3. First run, no upload:  .\.venv\Scripts\python.exe -m src.pipeline --no-upload"
Write-Host "  4. Real run:              .\run_daily.ps1"
