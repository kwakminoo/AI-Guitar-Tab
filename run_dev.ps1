Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
Write-Host "백엔드(8000)와 프론트(3000)를 각각 새 PowerShell 창에서 띄웁니다." -ForegroundColor Cyan
Write-Host "브라우저: http://localhost:3000  |  API: http://127.0.0.1:8000/docs" -ForegroundColor Green

$backendScript = Join-Path $repoRoot "run_backend_py311.ps1"
Start-Process powershell -WorkingDirectory $repoRoot -ArgumentList @(
  "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $backendScript
)

Start-Sleep -Seconds 2

$frontendDir = Join-Path $repoRoot "frontend"
Start-Process powershell -WorkingDirectory $frontendDir -ArgumentList @(
  "-NoExit", "-Command", "npm run dev"
)
