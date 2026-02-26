# AGENTS.md

## Cursor Cloud specific instructions

### Project Overview
AI Guitar Tab Generator — 음악 파일을 업로드하면 AI가 기타 코드/타브 악보를 자동 생성하는 웹 앱. React 프론트엔드 + FastAPI 백엔드 구조.

### Services
| Service | Port | Run Command |
|---------|------|-------------|
| Backend (FastAPI) | 8000 | `cd backend && source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000 --reload` |
| Frontend (React) | 3000 | `cd frontend && npm start` |

### Important Notes

- **Python 3.11 필수**: `requirements.txt`의 일부 패키지(tensorflow 2.13.0)가 Python 3.12와 호환되지 않으므로 `python3.11`을 사용해 venv을 생성해야 합니다. 시스템에 deadsnakes PPA를 통해 Python 3.11이 설치되어 있습니다.
- **requirements.txt 버전 이슈**: `aiofiles==0.24.0` (존재하지 않는 버전), `chord-extractor==0.1.0` (해당 버전 없음), `tensorflow==2.13.0` (typing-extensions 충돌) 세 패키지는 직접 설치 불가. 실제 코드에서 tensorflow/chord-extractor는 import하지 않으므로 이를 제외하고 `aiofiles`는 버전 제약 없이 설치하면 됩니다.
- **시스템 의존성**: `ffmpeg`, `libsndfile1`, `gcc`, `g++` 가 필요합니다 (현재 설치됨).
- **Lint**: `cd frontend && npx eslint src/` (warning만 있고 error 없음)
- **Tests**: 프론트엔드 테스트 파일 없음. `CI=true npm test -- --watchAll=false --passWithNoTests`로 통과.
- **Build**: `cd frontend && npm run build`
- **기존 코드 버그**: 합성 오디오로 `/analyze` 엔드포인트 테스트 시 chord_extractor.py에서 `tuple index out of range` 에러 발생. 이는 beat 정보 처리 로직 버그로, 환경 설정 문제가 아닙니다.
