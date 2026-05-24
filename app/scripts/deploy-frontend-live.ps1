# Deploy Firebase Hosting (frontend entry point → redirects to live Flask backend).
# Usage: powershell -ExecutionPolicy Bypass -File app\scripts\deploy-frontend-live.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$HostingDir = Join-Path $Root "smartdrivevision"

Set-Location $HostingDir

$configPath = Join-Path $HostingDir "public\config.js"
$config = Get-Content $configPath -Raw
if ($config -match "SMARTDRIVE_API\s*=\s*'([^']*)'") {
    $url = $Matches[1].Trim()
    if (-not $url) {
        Write-Host "`nSet your backend URL in smartdrivevision/public/config.js first." -ForegroundColor Red
        Write-Host "Run run-backend-live.ps1 and paste the trycloudflare.com URL.`n" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "Frontend will redirect to: $url" -ForegroundColor Green
}

Write-Host "`n=== Deploying Firebase Hosting ===" -ForegroundColor Cyan
firebase deploy --only hosting
Write-Host "`nLive frontend URL: https://smartdrive-vision.web.app (or your Firebase domain)" -ForegroundColor Green
