# Omnizart 전용 Python 3.8 가상환경 생성 (공식 패키지는 Python < 3.9).
# Windows에서 madmom 빌드: Cython + wheel 선설치 후 --no-build-isolation.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $backendDir ".venv_omnizart"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
  throw "Python launcher (py) 가 필요합니다."
}

Write-Host "Using Python 3.8 for Omnizart venv..." -ForegroundColor Cyan
& py -3.8 -V

if (-not (Test-Path $venvDir)) {
  Write-Host "Creating $venvDir ..." -ForegroundColor Cyan
  & py -3.8 -m venv $venvDir
}

$pip = Join-Path $venvDir "Scripts\pip.exe"
$python = Join-Path $venvDir "Scripts\python.exe"
& $pip install --upgrade pip wheel setuptools
& $pip install "Cython<3" numpy
& $pip install madmom==0.16.1 --no-build-isolation
& $pip install omnizart==0.5.0

$fs = Join-Path $venvDir "Lib\site-packages\fluidsynth.py"
$patchScript = Join-Path $PSScriptRoot "patch_omnizart_fluidsynth.py"
if ((Test-Path $fs) -and (Test-Path $patchScript)) {
  Write-Host "Patching fluidsynth.py for Windows DLL path..." -ForegroundColor Cyan
  & $python $patchScript $fs
}

Write-Host "Downloading Omnizart checkpoints (large download)..." -ForegroundColor Cyan
$env:PYTHONUTF8 = "1"
& (Join-Path $venvDir "Scripts\omnizart.exe") download-checkpoints

Write-Host "Done. Backend will use: $python" -ForegroundColor Green
