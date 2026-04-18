Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

chcp 65001 > $null

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "UTF-8 shell ready for this repo." -ForegroundColor Green
Write-Host "PowerShell code page: 65001" -ForegroundColor DarkGray
Write-Host "PYTHONUTF8=1, PYTHONIOENCODING=utf-8" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Use this at repo root:" -ForegroundColor Cyan
Write-Host ". .\\scripts\\dev-utf8.ps1" -ForegroundColor White
