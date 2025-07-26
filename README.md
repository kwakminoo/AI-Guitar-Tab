# 🎸 AI 기반 기타 타브악보 자동 생성기

노래나 영상 파일을 입력하면 AI가 자동으로 기타 코드, 타브 악보, 카포 위치, 키 조절, 아르페지오/스트로크 연주 비율을 분석해주는 웹사이트입니다.

![Demo](https://via.placeholder.com/800x400/667eea/ffffff?text=AI+Guitar+Tab+Generator)

---

## 🎵 주요 기능

- **🎵 AI 음성 분석**: 업로드된 음악 파일에서 자동으로 코드 진행을 추출
- **🎸 기타 타브 악보 생성**: 분석된 코드를 기반으로 실제 연주 가능한 타브 악보 생성
- **🔄 실시간 키 변환**: 원하는 키로 즉시 변환 (-12 ~ +12 반음)
- **📏 카포 위치 설정**: 카포 사용 시 코드 자동 변환 (0~12프렛)
- **🎼 연주 스타일 조절**: 아르페지오와 스트로크 비율을 슬라이더로 조절
- **📄 악보 다운로드**: PDF, TXT 형태로 악보 내보내기
- **🎯 직관적인 UI**: 드래그 앤 드롭 파일 업로드, 실시간 미리보기

---

## 🛠 기술 스택

### 백엔드
- **Python 3.9+** with FastAPI
- **Librosa**: 오디오 신호 처리 및 분석
- **NumPy/SciPy**: 수치 계산 및 신호 처리
- **FFmpeg**: 비디오 파일에서 오디오 추출
- **PyDub**: 오디오 파일 형식 변환

### 프론트엔드
- **React 18** with Hooks
- **TailwindCSS**: 반응형 UI 디자인
- **Axios**: API 통신
- **React Dropzone**: 파일 업로드 UI
- **html2canvas & jsPDF**: 악보 출력 기능

### 지원 파일 형식
- **오디오**: MP3, WAV, M4A (최대 100MB)
- **비디오**: MP4, AVI, MOV (오디오 자동 추출)

---

## 🚀 빠른 시작

### 1. 자동 설치 및 실행 (권장)

```bash
# 프로젝트 클론
git clone [repository-url]
cd ai-guitar-tab-generator

# 자동 설치 및 실행
./run.sh
```

실행 후 브라우저에서 `http://localhost:3000`을 열어주세요!

### 2. 수동 설치

#### 시스템 요구사항
- Python 3.8+
- Node.js 16+
- FFmpeg (선택사항, 비디오 파일 처리용)

#### 백엔드 설정
```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

#### 프론트엔드 설정
```bash
cd frontend
npm install
npm start
```

### 3. Docker로 실행
```bash
docker-compose up --build
```

---

## 📖 사용법

1. **파일 업로드**: 메인 페이지에서 음악/영상 파일을 드래그 앤 드롭
2. **분석 대기**: AI가 코드와 키를 자동으로 분석 (1-5분 소요)
3. **설정 조절**: 키 변경, 카포 위치, 연주 스타일을 원하는 대로 조절
4. **결과 확인**: 생성된 코드 차트와 타브 악보를 확인
5. **다운로드**: PDF 또는 TXT 형태로 악보 저장

### 💡 더 좋은 결과를 위한 팁
- 보컬과 기타가 명확하게 들리는 곡을 선택하세요
- 너무 복잡하지 않은 편곡의 곡이 더 정확합니다
- 고음질 파일일수록 더 정확한 분석이 가능합니다
- 인트로보다는 메인 멜로디 부분이 포함된 구간을 추천합니다

---

## 🏗 프로젝트 구조

```
ai-guitar-tab-generator/
├── backend/                 # Python FastAPI 서버
│   ├── main.py             # 메인 API 엔드포인트
│   ├── audio_analyzer.py   # 오디오 분석 모듈
│   ├── chord_extractor.py  # 코드 추출 모듈
│   ├── tab_generator.py    # 타브 악보 생성 모듈
│   └── requirements.txt    # Python 의존성
├── frontend/               # React 웹 애플리케이션
│   ├── src/
│   │   ├── components/     # React 컴포넌트
│   │   ├── services/       # API 서비스
│   │   └── App.js         # 메인 애플리케이션
│   └── package.json       # Node.js 의존성
├── run.sh                 # 자동 실행 스크립트
├── stop.sh                # 서버 종료 스크립트
└── docker-compose.yml     # Docker 설정
```

---

## 🔧 API 엔드포인트

### POST `/analyze`
음악 파일을 분석하여 코드와 타브 악보를 생성합니다.

**파라미터:**
- `file`: 음성/영상 파일
- `key_change`: 키 변경 (반음 단위, -12~12)
- `capo_position`: 카포 위치 (0~12)
- `arpeggio_ratio`: 아르페지오 비율 (0.0~1.0)

**응답:**
```json
{
  "success": true,
  "filename": "example.mp3",
  "analysis": {
    "key": "C",
    "tempo": 120,
    "duration": 180.5
  },
  "chords": [...],
  "tab": {...}
}
```

### POST `/transpose`
기존 코드를 이조합니다.

### POST `/generate-tab`
기존 코드로부터 타브 악보를 재생성합니다.

API 문서: `http://localhost:8000/docs`

---

## 🔍 알고리즘 및 기술

### 음성 분석
- **크로마그램 분석**: 각 시간대별 음정 성분 추출
- **비트 트래킹**: 곡의 템포와 박자 감지
- **키 추정**: Krumhansl-Schmuckler 알고리즘 사용

### 코드 인식
- **템플릿 매칭**: 메이저/마이너 코드 템플릿과 비교
- **시간 세그멘테이션**: 비트 단위로 코드 변화 감지
- **후처리**: 연속된 같은 코드 병합 및 노이즈 제거

### 타브 생성
- **코드 포지션 매핑**: 각 코드의 기타 핑거링 정보
- **연주 패턴**: 아르페지오/스트로크 패턴 생성
- **마디 구성**: 4/4 박자 기준 마디별 구성

---

## 🚨 문제 해결

### 일반적인 문제들

#### 1. 백엔드 서버가 시작되지 않음
```bash
# 의존성 재설치
cd backend
pip install --upgrade pip
pip install -r requirements.txt

# 포트 충돌 확인
lsof -i :8000
```

#### 2. 프론트엔드 빌드 오류
```bash
# node_modules 재설치
cd frontend
rm -rf node_modules package-lock.json
npm install
```

#### 3. 파일 업로드 실패
- 파일 크기가 100MB 이하인지 확인
- 지원하는 파일 형식인지 확인 (MP3, WAV, M4A, MP4, AVI, MOV)
- 브라우저 콘솔에서 에러 메시지 확인

#### 4. 분석 결과가 부정확함
- 더 고음질의 파일을 사용해보세요
- 배경음이 적고 기타 소리가 명확한 곡을 선택하세요
- 너무 복잡한 편곡보다는 단순한 어쿠스틱 버전을 추천합니다

### 로그 확인
```bash
# 백엔드 로그
tail -f backend/backend.log

# 프론트엔드 로그
tail -f frontend/frontend.log
```

---

## 🤝 기여하기

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📜 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.

---

## 🙏 감사의 글

- [Librosa](https://librosa.org/) - 오디오 분석 라이브러리
- [FastAPI](https://fastapi.tiangolo.com/) - 현대적인 Python 웹 프레임워크
- [React](https://reactjs.org/) - 사용자 인터페이스 라이브러리
- [TailwindCSS](https://tailwindcss.com/) - 유틸리티 우선 CSS 프레임워크

---

## 📞 문의

프로젝트 관련 문의사항이나 버그 리포트는 GitHub Issues를 이용해주세요.

**Made with ❤️ for guitar players everywhere** 🎸

