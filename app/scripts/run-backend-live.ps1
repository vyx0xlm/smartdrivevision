# Run Flask backend with a public HTTPS URL (free Cloudflare tunnel).
# Usage: powershell -ExecutionPolicy Bypass -File app\scripts\run-backend-live.ps1

$ErrorActionPreference = "Stop"
$AppDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$AppFolder = Join-Path $AppDir "app"

Set-Location $AppFolder

Write-Host "`n=== SmartDrive backend (live) ===" -ForegroundColor Cyan

python -m pip install -r requirements.txt -q
python -c "from app import init_db; init_db()"

$env:BEHIND_PROXY = "1"
$env:FLASK_DEBUG = "0"
$env:PORT = "5000"

# Start Waitress (works on Windows; gunicorn is Linux-only)
$backend = Start-Process python -ArgumentList @(
    "-m", "waitress",
    "--host=0.0.0.0",
    "--port=5000",
    "app:app"
) -PassThru -WindowStyle Hidden

Start-Sleep -Seconds 2
Write-Host "Backend running locally on http://127.0.0.1:5000 (PID $($backend.Id))" -ForegroundColor Green

# Cloudflare tunnel
$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
    Write-Host "`ncloudflared not found. Install it:" -ForegroundColor Yellow
    Write-Host "  winget install Cloudflare.cloudflared" -ForegroundColor White
    Write-Host "`nOr download: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" -ForegroundColor Gray
    Write-Host "`nBackend is still running locally. Press Enter to stop..." -ForegroundColor Yellow
    Read-Host
    Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "`nStarting Cloudflare tunnel (public HTTPS URL below)..." -ForegroundColor Cyan
Write-Host "Copy the https://....trycloudflare.com URL into smartdrivevision/public/config.js`n" -ForegroundColor Yellow

try {
    cloudflared tunnel --url http://127.0.0.1:5000
} finally {
    Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    Write-Host "Backend stopped." -ForegroundColor Gray
}
