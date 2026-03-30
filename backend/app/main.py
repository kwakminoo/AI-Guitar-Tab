import asyncio
import json
import queue
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl

from .services.pipeline import run_four_step_pipeline

app = FastAPI(title="AI Guitar Tab Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PipelineRequest(BaseModel):
    url: HttpUrl


class PipelineResponse(BaseModel):
    job_dir: str
    mp3_path: str
    stems: dict[str, str]
    midi_path: str
    alphatex: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/pipeline/run", response_model=PipelineResponse)
async def pipeline_run(payload: PipelineRequest) -> PipelineResponse:
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(run_four_step_pipeline, str(payload.url)),
            timeout=1800.0,
        )
        return PipelineResponse(
            job_dir=str(result.job_dir),
            mp3_path=str(result.mp3_path),
            stems={k: str(v) for k, v in result.stems.items()},
            midi_path=str(result.midi_path),
            alphatex=result.alphatex,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="파이프라인 실행 시간이 30분을 초과했습니다.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/pipeline/run-stream")
async def pipeline_run_stream(url: HttpUrl):
    q: "queue.Queue[dict]" = queue.Queue()

    def report(ev: dict[str, Any]) -> None:
        q.put(ev)

    def run() -> None:
        try:
            result = run_four_step_pipeline(str(url), progress_cb=report)
            q.put(
                {
                    "type": "done",
                    "payload": {
                        "job_dir": str(result.job_dir),
                        "mp3_path": str(result.mp3_path),
                        "stems": {k: str(v) for k, v in result.stems.items()},
                        "midi_path": str(result.midi_path),
                        "alphatex": result.alphatex,
                    },
                }
            )
        except Exception as exc:
            q.put({"type": "error", "detail": str(exc)})

    asyncio.get_running_loop().run_in_executor(None, run)

    async def gen():
        while True:
            ev = await asyncio.to_thread(q.get)
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if ev.get("type") in ("done", "error"):
                break

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
