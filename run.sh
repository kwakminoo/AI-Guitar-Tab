#!/bin/bash

# 🎸 AI 기타 타브 생성기 실행 스크립트

echo "🎸 AI 기타 타브 생성기를 시작합니다..."

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 에러 처리 함수
handle_error() {
    echo -e "${RED}❌ 오류가 발생했습니다: $1${NC}"
    exit 1
}

# 성공 메시지 함수
success_message() {
    echo -e "${GREEN}✅ $1${NC}"
}

# 정보 메시지 함수
info_message() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# 경고 메시지 함수
warning_message() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# 시스템 요구사항 확인
info_message "시스템 요구사항을 확인합니다..."

# Python 확인
if ! command -v python3 &> /dev/null; then
    handle_error "Python3이 설치되어 있지 않습니다. Python 3.8 이상을 설치해주세요."
fi

# Node.js 확인
if ! command -v node &> /dev/null; then
    handle_error "Node.js가 설치되어 있지 않습니다. Node.js 16 이상을 설치해주세요."
fi

# npm 확인
if ! command -v npm &> /dev/null; then
    handle_error "npm이 설치되어 있지 않습니다."
fi

success_message "시스템 요구사항 확인 완료"

# FFmpeg 확인 (선택사항)
if ! command -v ffmpeg &> /dev/null; then
    warning_message "FFmpeg이 설치되어 있지 않습니다. 비디오 파일 처리가 제한될 수 있습니다."
    warning_message "Ubuntu/Debian: sudo apt install ffmpeg"
    warning_message "macOS: brew install ffmpeg"
    warning_message "Windows: https://ffmpeg.org/download.html"
fi

# 백엔드 설정
echo
info_message "백엔드를 설정합니다..."
cd backend || handle_error "backend 폴더를 찾을 수 없습니다."

# 가상환경 생성 및 활성화
if [ ! -d "venv" ]; then
    info_message "Python 가상환경을 생성합니다..."
    python3 -m venv venv || handle_error "가상환경 생성에 실패했습니다."
fi

# 가상환경 활성화
info_message "가상환경을 활성화합니다..."
source venv/bin/activate || handle_error "가상환경 활성화에 실패했습니다."

# 의존성 설치
info_message "Python 의존성을 설치합니다... (시간이 걸릴 수 있습니다)"
pip install --upgrade pip
pip install -r requirements.txt || handle_error "Python 의존성 설치에 실패했습니다."

success_message "백엔드 설정 완료"

# 프론트엔드 설정
echo
info_message "프론트엔드를 설정합니다..."
cd ../frontend || handle_error "frontend 폴더를 찾을 수 없습니다."

# Node.js 의존성 설치
if [ ! -d "node_modules" ]; then
    info_message "Node.js 의존성을 설치합니다... (시간이 걸릴 수 있습니다)"
    npm install || handle_error "Node.js 의존성 설치에 실패했습니다."
fi

success_message "프론트엔드 설정 완료"

# 서버 실행
echo
info_message "서버를 시작합니다..."

# 백엔드 서버 실행 (백그라운드)
cd ../backend
info_message "백엔드 서버를 시작합니다... (http://localhost:8000)"
source venv/bin/activate
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload > backend.log 2>&1 &
BACKEND_PID=$!

# 백엔드 서버 시작 확인
sleep 3
if ! ps -p $BACKEND_PID > /dev/null; then
    handle_error "백엔드 서버 시작에 실패했습니다. backend.log를 확인해주세요."
fi

success_message "백엔드 서버가 시작되었습니다 (PID: $BACKEND_PID)"

# 프론트엔드 서버 실행
cd ../frontend
info_message "프론트엔드 서버를 시작합니다... (http://localhost:3000)"
nohup npm start > frontend.log 2>&1 &
FRONTEND_PID=$!

# 프론트엔드 서버 시작 확인
sleep 5
if ! ps -p $FRONTEND_PID > /dev/null; then
    handle_error "프론트엔드 서버 시작에 실패했습니다. frontend.log를 확인해주세요."
fi

success_message "프론트엔드 서버가 시작되었습니다 (PID: $FRONTEND_PID)"

# 서버 상태 저장
cd ..
echo "$BACKEND_PID" > .backend_pid
echo "$FRONTEND_PID" > .frontend_pid

echo
echo "🎉 서버가 성공적으로 시작되었습니다!"
echo
echo "📱 웹사이트: http://localhost:3000"
echo "🔧 API 서버: http://localhost:8000"
echo "📚 API 문서: http://localhost:8000/docs"
echo
echo "서버를 중지하려면: ./stop.sh"
echo "로그를 확인하려면:"
echo "  - 백엔드: tail -f backend/backend.log"
echo "  - 프론트엔드: tail -f frontend/frontend.log"
echo
info_message "브라우저에서 http://localhost:3000 을 열어주세요!"

# 브라우저 자동 열기 (선택사항)
if command -v xdg-open &> /dev/null; then
    sleep 2
    xdg-open http://localhost:3000 &
elif command -v open &> /dev/null; then
    sleep 2
    open http://localhost:3000 &
fi