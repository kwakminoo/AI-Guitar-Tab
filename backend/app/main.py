import asyncio
from urllib.parse import urlparse
from typing import Any

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

from .services.pipeline import _midi_to_alphatex, _midi_to_score, run_four_step_pipeline

app = FastAPI(title="AI Guitar Tab Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PipelineRequest(BaseModel):
    url: HttpUrl
    jobId: str | None = None


def _is_supported_youtube_url(raw_url: str) -> bool:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


class YoutubeTabPreviewResponse(BaseModel):
    title: str
    artist: str
    lyrics: str | None = None
    score: dict[str, Any]
    alphatex: str


class MidiTabPreviewResponse(BaseModel):
    title: str
    score: dict[str, Any]
    alphatex: str


class PipelineProgressResponse(BaseModel):
    progress: int
    stage: str
    detail: str
    done: bool = False
    error: str | None = None


_PIPELINE_PROGRESS: dict[str, dict[str, Any]] = {}


def _sanitize_upload_filename(filename: str) -> str:
    base = Path(filename).name.strip() or "uploaded.mid"
    safe = "".join(ch for ch in base if ch.isalnum() or ch in ("-", "_", ".", " "))
    safe = safe.strip().replace(" ", "_")
    if not safe:
        safe = "uploaded.mid"
    return safe


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/youtube/tab-preview", response_model=YoutubeTabPreviewResponse)
async def youtube_tab_preview(payload: PipelineRequest) -> YoutubeTabPreviewResponse:
    progress_id = (payload.jobId or "").strip() or f"job-{id(payload)}"
    try:
        if not _is_supported_youtube_url(str(payload.url)):
            raise HTTPException(status_code=400, detail="유튜브 URL만 지원합니다.")
        _PIPELINE_PROGRESS[progress_id] = {
            "progress": 0,
            "stage": "queued",
            "detail": "요청 수신",
            "done": False,
            "error": None,
        }

        def _on_progress(evt: dict[str, Any]) -> None:
            _PIPELINE_PROGRESS[progress_id] = {
                "progress": int(evt.get("progress", 0)),
                "stage": str(evt.get("stage", "running")),
                "detail": str(evt.get("detail", "")),
                "done": False,
                "error": None,
            }

        result = await asyncio.wait_for(
            asyncio.to_thread(run_four_step_pipeline, str(payload.url), progress_cb=_on_progress),
            timeout=1800.0,
        )
        _PIPELINE_PROGRESS[progress_id] = {
            "progress": 100,
            "stage": "done",
            "detail": "완료",
            "done": True,
            "error": None,
        }
        return YoutubeTabPreviewResponse(
            title=result.title,
            artist=result.artist,
            lyrics=result.lyrics,
            score=result.score,
            alphatex=result.alphatex,
        )
    except TimeoutError as exc:
        _PIPELINE_PROGRESS[progress_id] = {
            "progress": int(_PIPELINE_PROGRESS.get(progress_id, {}).get("progress", 0)),
            "stage": "timeout",
            "detail": "분석 시간이 30분을 초과했습니다.",
            "done": True,
            "error": "timeout",
        }
        raise HTTPException(status_code=504, detail="분석 시간이 30분을 초과했습니다.") from exc
    except Exception as exc:
        _PIPELINE_PROGRESS[progress_id] = {
            "progress": int(_PIPELINE_PROGRESS.get(progress_id, {}).get("progress", 0)),
            "stage": "error",
            "detail": str(exc),
            "done": True,
            "error": str(exc),
        }
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/youtube/tab-preview/progress/{job_id}", response_model=PipelineProgressResponse)
async def youtube_tab_preview_progress(job_id: str) -> PipelineProgressResponse:
    item = _PIPELINE_PROGRESS.get(job_id)
    if not item:
        return PipelineProgressResponse(progress=0, stage="idle", detail="대기 중", done=False, error=None)
    return PipelineProgressResponse(
        progress=int(item.get("progress", 0)),
        stage=str(item.get("stage", "running")),
        detail=str(item.get("detail", "")),
        done=bool(item.get("done", False)),
        error=item.get("error"),
    )


@app.post("/api/midi/tab-preview", response_model=MidiTabPreviewResponse)
async def midi_tab_preview(file: UploadFile = File(...)) -> MidiTabPreviewResponse:
    try:
        filename = _sanitize_upload_filename(file.filename or "uploaded.mid")
        lower_name = filename.lower()
        if not (lower_name.endswith(".mid") or lower_name.endswith(".midi")):
            raise HTTPException(status_code=400, detail="MIDI 파일(.mid, .midi)만 지원합니다.")

        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="업로드한 MIDI 파일이 비어 있습니다.")

        uploads_dir = Path("data") / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        midi_path = uploads_dir / filename
        midi_path.write_bytes(data)

        title = Path(filename).stem or "Uploaded MIDI"
        score = _midi_to_score(midi_path, title=title)
        alphatex = _midi_to_alphatex(midi_path, title=title)
        return MidiTabPreviewResponse(title=title, score=score, alphatex=alphatex)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
