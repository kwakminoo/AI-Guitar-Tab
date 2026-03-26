# 저장소 루트에서 실행: 올바른 백엔드(backend/app/main.py)를 띄웁니다.
Set-Location "$PSScriptRoot\backend"
Write-Host "cwd=$PWD -> uvicorn app.main:app" -ForegroundColor Green
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
