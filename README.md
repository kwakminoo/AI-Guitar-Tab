# AI Guitar Tab (Audio Server)

유튜브 URL을 입력받아 `yt-dlp`로 **최고 음질 오디오를 WAV로 다운로드**하는 FastAPI 서버입니다.

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

추가로 **FFmpeg 설치가 필요**합니다 (`ffmpeg` 실행 파일이 PATH에 있어야 함).

## 실행

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API

- `POST /api/audio/youtube-to-wav`
  - 요청: `{ "youtube_url": "https://www.youtube.com/watch?v=..." }`
  - 응답: `{ "id": "<uuid>", "wav_path": "data/audio/<uuid>.wav" }`

