Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$venvDir = Join-Path $backendDir ".venv311"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
  throw "Windows Python launcher(py)가 없습니다. Python 3.11 설치 후 다시 시도하세요."
}

Write-Host "Checking Python 3.11..." -ForegroundColor Cyan
& py -3.11 -V

if (-not (Test-Path $venvDir)) {
  Write-Host "Creating .venv311..." -ForegroundColor Cyan
  & py -3.11 -m venv $venvDir
}

$pythonExe = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
  throw ".venv311 python 실행 파일을 찾을 수 없습니다: $pythonExe"
}

Write-Host "Installing dependencies (py311 profile)..." -ForegroundColor Cyan
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r (Join-Path $backendDir "requirements-py311.txt")
Write-Host "Skip optional madmom install (Windows 빌드 오류 방지)." -ForegroundColor Yellow
Write-Host "필요할 때만 수동 설치: .venv311\\Scripts\\python.exe -m pip install madmom==0.16.1 --no-build-isolation" -ForegroundColor Yellow

$ensureFret = Join-Path $backendDir "scripts\ensure_fret_t5_vendor.ps1"
if (Test-Path $ensureFret) {
  Write-Host "Ensuring Fret-T5 vendor (Jazvie/t5_fretting_transformer)..." -ForegroundColor Cyan
  try {
    & $ensureFret
    $vendorFret = Join-Path $backendDir "vendor\t5_fretting_transformer"
    if (Test-Path (Join-Path $vendorFret "pyproject.toml")) {
      & $pythonExe -m pip install -e $vendorFret
    }
  } catch {
    Write-Host "Fret-T5 vendor 설치를 건너뜁니다(선택). 파이프라인은 MIDI 폴백으로 동작합니다." -ForegroundColor Yellow
  }
}

Set-Location $backendDir
Write-Host "Starting backend on 127.0.0.1:8000 using Python 3.11" -ForegroundColor Green
& $pythonExe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
