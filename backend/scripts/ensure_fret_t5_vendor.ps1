Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$backendRoot = Split-Path $PSScriptRoot -Parent
$pkg = Join-Path $backendRoot "packaging\fret_t5_pyproject.toml"
$dest = Join-Path $backendRoot "vendor\t5_fretting_transformer"

if (-not (Test-Path $pkg)) {
  throw "패키징용 pyproject가 없습니다: $pkg"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host "git이 PATH에 없어 Fret-T5 벤더 클론을 건너뜁니다." -ForegroundColor Yellow
  exit 0
}

if (-not (Test-Path (Join-Path $dest "src\fret_t5"))) {
  Write-Host "Cloning t5_fretting_transformer -> $dest" -ForegroundColor Cyan
  New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
  git clone --depth 1 https://github.com/Jazvie/t5_fretting_transformer.git $dest
}

Copy-Item -Force $pkg (Join-Path $dest "pyproject.toml")
Write-Host "Fret-T5 vendor 준비 완료: $dest" -ForegroundColor Green
