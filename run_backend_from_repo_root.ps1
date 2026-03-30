# 저장소 루트에서 실행: 올바른 백엔드(backend/app/main.py)를 띄웁니다.
Set-Location "$PSScriptRoot\backend"
Write-Host "cwd=$PWD -> uvicorn app.main:app" -ForegroundColor Green
# 장시간 오디오 분석 중에는 --reload가 소켓 리셋(ECONNRESET)을 유발할 수 있어 비활성화
uvicorn app.main:app --host 127.0.0.1 --port 8000
