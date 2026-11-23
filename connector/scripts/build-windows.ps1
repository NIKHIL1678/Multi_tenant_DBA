# Builds the one-file Windows connector and puts it where the dashboard serves downloads.
#
#   cd connector
#   powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
#
# Result: connector\dist\zipzy-connector.exe, copied to dashboard\public\downloads\
# (then `npm run build` in dashboard so the built site includes it). The .exe is never committed.

$ErrorActionPreference = "Stop"
$connector = Split-Path $PSScriptRoot -Parent
Set-Location $connector

uv sync --locked
uv run --with "pyinstaller==6.22.3" pyinstaller `
    --noconfirm --clean --onefile --console `
    --name zipzy-connector `
    --collect-submodules zipzy_connector `
    --collect-submodules asyncpg `
    --collect-submodules aiomysql `
    --collect-submodules pymysql `
    packaging\entry.py

$downloads = Join-Path (Split-Path $connector -Parent) "dashboard\public\downloads"
New-Item -ItemType Directory -Force $downloads | Out-Null
Copy-Item "dist\zipzy-connector.exe" $downloads -Force

Write-Host ""
Write-Host "Built dist\zipzy-connector.exe and copied it to $downloads"
Write-Host "Now run 'npm run build' in the dashboard folder so the download is included."
