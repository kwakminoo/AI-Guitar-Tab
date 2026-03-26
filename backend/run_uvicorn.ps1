# 타브 API가 있는 백엔드만 실행합니다. 반드시 backend 폴더를 cwd로 두고 app.main 을 로드합니다.
Set-Location $PSScriptRoot
Write-Host "Starting: uvicorn app.main:app (cwd=$PWD)" -ForegroundColor Green
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
