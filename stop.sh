#!/bin/bash

# 🎸 AI 기타 타브 생성기 종료 스크립트

echo "🛑 AI 기타 타브 생성기를 종료합니다..."

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# PID 파일에서 프로세스 종료
if [ -f ".backend_pid" ]; then
    BACKEND_PID=$(cat .backend_pid)
    if ps -p $BACKEND_PID > /dev/null; then
        info_message "백엔드 서버를 종료합니다... (PID: $BACKEND_PID)"
        kill $BACKEND_PID
        success_message "백엔드 서버가 종료되었습니다"
    else
        warning_message "백엔드 서버가 이미 종료되었습니다"
    fi
    rm .backend_pid
else
    warning_message "백엔드 PID 파일을 찾을 수 없습니다"
fi

if [ -f ".frontend_pid" ]; then
    FRONTEND_PID=$(cat .frontend_pid)
    if ps -p $FRONTEND_PID > /dev/null; then
        info_message "프론트엔드 서버를 종료합니다... (PID: $FRONTEND_PID)"
        kill $FRONTEND_PID
        success_message "프론트엔드 서버가 종료되었습니다"
    else
        warning_message "프론트엔드 서버가 이미 종료되었습니다"
    fi
    rm .frontend_pid
else
    warning_message "프론트엔드 PID 파일을 찾을 수 없습니다"
fi

# 추가 정리
info_message "남은 프로세스를 정리합니다..."

# uvicorn 프로세스 종료
pkill -f "uvicorn main:app" 2>/dev/null && success_message "남은 백엔드 프로세스를 종료했습니다"

# React 개발 서버 종료
pkill -f "react-scripts start" 2>/dev/null && success_message "남은 프론트엔드 프로세스를 종료했습니다"

echo
success_message "모든 서버가 종료되었습니다"
info_message "다시 시작하려면: ./run.sh"