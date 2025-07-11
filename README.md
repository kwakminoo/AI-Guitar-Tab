# 🎸 AI 기반 기타 타브악보 자동 생성기

노래나 영상 파일을 입력하면 AI가 자동으로 기타 코드, 타브 악보, 가사, 카포 위치, 키 조절, 아르페지오/스트로크 연주 비율을 분석해주는 웹사이트 기반 프로젝트입니다.

---

## 🧠 주요 기능

- 🎵 음원/영상 분석 → 코드 자동 추출 (AI 기반)
- 📝 가사 + 코드 동기화 표시
- 🎸 기타 타브 악보 자동 생성
- 🔁 키 변환 기능 (남자키 ↔ 여자키)
- 🎚 아르페지오/스트로크 비율 조절 및 구간 지정
- 📄 악보 출력 (PDF or 이미지 형태)
- 🎧 실시간 코드/악보 미리보기

---

## 🛠 기술 스택

| 구성 | 기술 |
|------|------|
| 프론트엔드 | React + TailwindCSS |
| 백엔드 | Python + FastAPI |
| 음원 분석 | Librosa, Spleeter, pyAudioAnalysis, Chord Extraction ML |
| 데이터베이스 | MongoDB (사용자 악보 저장) |
| 배포 예정 | Vercel (프론트) + Render (백엔드) |

---

## 🧪 향후 계획

- [ ] 사용자별 악보 저장 기능
- [ ] 유튜브 링크 분석 기능
- [ ] 자동 연주 영상 생성
- [ ] 모바일 앱 버전 확장

---


---

## 📦 설치 및 실행 (로컬 개발)

```bash
# 백엔드
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# 프론트엔드
cd frontend
npm install
npm run dev


## 커서 프롬프트
~~~

---

## 💻 2. Cursor용 프롬프트

```text
🎸 프로젝트 개요:
노래나 영상을 업로드하면 자동으로 기타 타브악보를 생성해주는 웹 기반 도구를 만듭니다. AI를 활용해 코드/가사/키/카포를 분석하고, 사용자가 아르페지오와 스트로크 비율을 조절하거나 키를 바꿔서 악보를 출력할 수 있게 합니다.

🛠 지금부터 Cursor로 만들려는 구조는 다음과 같습니다:

1. `backend/` 폴더에 FastAPI 기반 서버를 생성합니다.
   - `/analyze` 엔드포인트에서 mp3/mp4 파일을 입력받고, 코드/키/가사 정보를 JSON으로 반환합니다.
   - 분석에 필요한 라이브러리는 `librosa`, `spleeter`, `chordino`, `pyin`, `pyDub` 등을 사용합니다.

2. `frontend/` 폴더에 React + Tailwind로 UI를 구성합니다.
   - 파일 업로드, 악보 미리보기, 아르페지오/스트로크 비율 조절 슬라이더, 키 전환 버튼, PDF 출력 버튼 등을 구현합니다.

3. `shared/` 폴더에는 악보 형식을 생성하는 템플릿 함수 및 유틸리티를 정의합니다.

⚠️ 먼저 백엔드 구조부터 잡고, 프론트엔드는 추후 연결합니다.

🧠 참고 라이브러리:
- Python: `librosa`, `fastapi`, `ffmpeg-python`, `spleeter`, `numpy`
- JS: `react`, `tailwindcss`, `axios`, `vexflow` (악보 렌더링)

👉 프로젝트 시작: `backend/` 폴더 생성 후 FastAPI 서버 세팅부터 시작해주세요.

~~~

