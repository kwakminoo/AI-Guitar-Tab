from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.services.audio_service import AudioService, default_audio_dir
from app.services.chord_analysis_service import (
    ChordAnalysisService,
    ChordAnalysisResult,
    ChordEvent,
)


app = FastAPI(title="AI Guitar Tab - Audio Server", version="0.1.0")


class YouTubeToWavRequest(BaseModel):
    youtube_url: str = Field(min_length=1, description="유튜브 영상 URL")


class YouTubeToWavResponse(BaseModel):
    id: str
    wav_path: str
    wav_path_abs: str


class ChordEventModel(BaseModel):
    time: float
    chord: str


class ChordAnalysisResponse(BaseModel):
    key: str
    chords: list[ChordEventModel]


class ChordAnalysisRequest(BaseModel):
    wav_path: str = Field(description="분리된 기타 트랙 WAV 파일의 경로 (서버 로컬 경로)")


@app.post("/api/audio/youtube-to-wav", response_model=YouTubeToWavResponse)
def youtube_to_wav(payload: YouTubeToWavRequest) -> YouTubeToWavResponse:
    output_dir = default_audio_dir()
    service = AudioService(output_dir=output_dir)

    try:
        result = service.download_youtube_to_wav(payload.youtube_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    wav_path_abs = result.wav_path
    wav_path_rel = _safe_relative_path(wav_path_abs, base_dir=Path.cwd())

    return YouTubeToWavResponse(
        id=result.id,
        wav_path=wav_path_rel.as_posix(),
        wav_path_abs=str(wav_path_abs),
    )


@app.post("/api/analyze/chords", response_model=ChordAnalysisResponse)
def analyze_chords(payload: ChordAnalysisRequest) -> ChordAnalysisResponse:
    service = ChordAnalysisService(frame_size_sec=1.0)
    try:
        result: ChordAnalysisResult = service.analyze_guitar_track(Path(payload.wav_path))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    chord_models = [
        ChordEventModel(time=ch.time, chord=ch.chord) for ch in result.chords
    ]
    return ChordAnalysisResponse(key=result.key, chords=chord_models)


def _safe_relative_path(path: Path, base_dir: Path) -> Path:
    try:
        return path.resolve().relative_to(base_dir.resolve())
    except Exception:
        return path.resolve()

