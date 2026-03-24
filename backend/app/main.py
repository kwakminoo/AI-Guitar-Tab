from pathlib import Path
import asyncio
import hashlib
import json
import math

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from typing import List

from .services.youtube import (
    download_audio_from_youtube,
    fetch_youtube_basic_meta,
    infer_song_meta_from_video_title,
)
from .services.separate import extract_guitar_stem
from .services.transcribe import transcribe_guitar_to_notes, NoteEvent
from .services.alphatab_mapper import beats_to_alphatab_score, notes_to_alphatab_score
from .services.harmony import analyze_harmony
from .services.rhythm import estimate_tempo_and_meter
from .services.lyrics import map_lyrics_to_beats


app = FastAPI(title="AI Guitar Tab Backend")

# Next.js dev 서버(로컬)에서 호출할 수 있도록 CORS 허용
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


class TimeSignature(BaseModel):
    numerator: int
    denominator: int


class AlphaTabNote(BaseModel):
    string: int
    fret: int
    start: float
    end: float


class AlphaTabBeat(BaseModel):
    time: float
    chord: str | None = None
    lyric: str | None = None
    notes: List[AlphaTabNote]


class AlphaTabTrack(BaseModel):
    name: str
    type: str
    strings: int
    tuning: List[int]
    beats: List[AlphaTabBeat]


class AlphaTabScore(BaseModel):
    version: int
    meta: dict
    tracks: List[AlphaTabTrack]


class FromYoutubeRequest(BaseModel):
    url: HttpUrl


class SongMetaResponse(BaseModel):
    title: str
    artist: str
    lyrics: str | None = None
    chords: List[str]
    key: str = "C major"
    capo: int = 0


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/song/meta", response_model=SongMetaResponse)
async def song_meta_from_youtube(payload: FromYoutubeRequest) -> SongMetaResponse:
    url = str(payload.url)
    if "youtube.com" not in url and "youtu.be" not in url:
        raise HTTPException(status_code=400, detail="지원하지 않는 URL 형식입니다.")

    try:
        meta = await asyncio.to_thread(fetch_youtube_basic_meta, url)
        inferred = await asyncio.to_thread(
            infer_song_meta_from_video_title,
            meta.get("video_title") or meta.get("title") or "",
            fallback_artist=meta.get("artist"),
        )
        # 메타 단계는 가볍게 가져오고, 코드/카포는 분석 단계에서 계산해 반영한다.
        chords = ["C", "G", "Am", "F"]
        return SongMetaResponse(
            title=inferred.get("title") or "Unknown Title",
            artist=inferred.get("artist") or "Unknown Artist",
            lyrics=inferred.get("lyrics"),
            chords=chords,
            key="C major",
            capo=0,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/score/from-youtube", response_model=AlphaTabScore)
async def score_from_youtube(payload: FromYoutubeRequest) -> AlphaTabScore:
    """
    유튜브 링크를 받아 기타 타브용 AlphaTabScore를 반환하는 엔드포인트.
    현재는 파이프라인이 완성되기 전까지 프론트의 데모와 동일한
    간단한 스코어를 반환한다.
    """
    url = str(payload.url)
    if "youtube.com" not in url and "youtu.be" not in url:
        raise HTTPException(status_code=400, detail="지원하지 않는 URL 형식입니다.")

    def run_pipeline() -> dict:
        work_dir = Path("data") / "jobs"
        work_dir.mkdir(parents=True, exist_ok=True)

        # 1) YouTube 오디오 다운로드
        audio_path = download_audio_from_youtube(
            str(payload.url),
            work_dir,
            audio_format="wav",
            max_seconds=30,
        )

        # 2) Demucs로 기타 스템 추출
        guitar_stem = extract_guitar_stem(audio_path, work_dir / "stems")

        # 3) 기타 전사
        notes = transcribe_guitar_to_notes(guitar_stem)

        # 3.5) 하모니 추정(키/카포/코드)
        harmony = analyze_harmony(notes, tempo=90)

        # 4) AlphaTabScore JSON으로 매핑
        score_dict = notes_to_alphatab_score(
            notes,
            title=fetch_youtube_basic_meta(str(payload.url)).get("title", "From YouTube"),
            tempo=90,
            key=harmony.key,
            capo=harmony.capo,
            chords=harmony.chords,
        )
        return score_dict

    try:
        # 무한 대기로 보이는 상황을 피하기 위해 전체 파이프라인 시간 제한을 둔다.
        # (다운로드 + 스템분리 + 전사 + 매핑)
        score_dict = await asyncio.wait_for(asyncio.to_thread(run_pipeline), timeout=420)
        return AlphaTabScore(**score_dict)
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="분석 시간이 제한(7분)을 초과했습니다. 다른 링크로 다시 시도해 주세요.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/score/from-youtube/stream")
async def score_from_youtube_stream(url: HttpUrl) -> StreamingResponse:
    """
    30초 구간에 대해 단계별 score를 스트리밍한다.
    - stage=grid: tempo/timeSignature + (있다면) syncedLyrics 기반 lyric 매핑, notes는 rests
    - stage=notes: 전사된 notes를 beat grid에 매핑
    - stage=harmony: bar 단위 chord 텍스트를 beat에 주입 + key/capo 확정
    """

    target_seconds = 30.0
    url_str = str(url)
    if "youtube.com" not in url_str and "youtu.be" not in url_str:
        raise HTTPException(status_code=400, detail="지원하지 않는 URL 형식입니다.")

    job_hash = hashlib.md5(url_str.encode("utf-8")).hexdigest()[:12]

    async def event_gen():
        work_dir = Path("data") / "jobs" / job_hash
        work_dir.mkdir(parents=True, exist_ok=True)

        def send_event(event: str, payload: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            # 1) 메타/가사 먼저
            meta = await asyncio.to_thread(fetch_youtube_basic_meta, url_str)
            inferred = await asyncio.to_thread(
                infer_song_meta_from_video_title,
                meta.get("video_title") or meta.get("title") or "",
                fallback_artist=meta.get("artist"),
            )
            title = str(inferred.get("title") or "From YouTube")
            artist = str(inferred.get("artist") or "Unknown Artist")
            lyrics = inferred.get("lyrics")

            # 2) 오디오 다운로드(30초)
            audio_path = await asyncio.to_thread(
                download_audio_from_youtube,
                url_str,
                work_dir / "audio",
                "wav",
                int(target_seconds),
            )

            # 3) BPM/메터 추정 + beat grid 생성
            tempo, time_signature_numerator, beat_times = await asyncio.to_thread(
                estimate_tempo_and_meter,
                str(audio_path),
                target_seconds=target_seconds,
            )

            # 4) lyric -> beat 매핑(타임코드 유무 자동 처리)
            lyrics_by_beat = map_lyrics_to_beats(lyrics, beat_times)

            # stage=grid: notes는 비워둔 rests 스코어
            empty_notes_by_beat: dict[int, List[NoteEvent]] = {}
            score_grid = beats_to_alphatab_score(
                beat_times,
                title=title,
                tempo=tempo,
                time_signature_numerator=time_signature_numerator,
                key="C major",
                capo=0,
                chords=[],
                notes_by_beat=empty_notes_by_beat,
                lyrics_by_beat=lyrics_by_beat,
                chord_by_beat=[None for _ in beat_times],
            )
            yield send_event(
                "message",
                {
                    "stage": "grid",
                    "progress": 20,
                    "title": title,
                    "artist": artist,
                    "lyrics": lyrics,
                    "score": score_grid,
                },
            )

            # 5) 기타 stem 추출
            guitar_stem = await asyncio.to_thread(
                extract_guitar_stem,
                Path(audio_path),
                work_dir / "stems",
            )

            # 6) 전사(notes)
            notes = await asyncio.to_thread(transcribe_guitar_to_notes, guitar_stem)

            # 7) notes -> beat 매핑(가장 가까운 beat에 배치)
            notes_by_beat: dict[int, List[NoteEvent]] = {}
            for ev in notes:
                mid = (float(ev.start) + float(ev.end)) / 2.0
                # nearest beat
                if not beat_times:
                    continue
                if mid < beat_times[0] or mid > beat_times[-1]:
                    continue

                # 이진 탐색으로 nearest
                lo, hi = 0, len(beat_times) - 1
                while lo < hi:
                    mid_i = (lo + hi) // 2
                    if beat_times[mid_i] < mid:
                        lo = mid_i + 1
                    else:
                        hi = mid_i
                idx2 = lo
                idx1 = max(0, idx2 - 1)
                beat_idx = idx1 if abs(beat_times[idx1] - mid) <= abs(beat_times[idx2] - mid) else idx2
                notes_by_beat.setdefault(beat_idx, []).append(ev)

            score_notes = beats_to_alphatab_score(
                beat_times,
                title=title,
                tempo=tempo,
                time_signature_numerator=time_signature_numerator,
                key="C major",
                capo=0,
                chords=[],
                notes_by_beat=notes_by_beat,
                lyrics_by_beat=lyrics_by_beat,
                chord_by_beat=[None for _ in beat_times],
            )
            yield send_event(
                "message",
                {
                    "stage": "notes",
                    "progress": 65,
                    "title": title,
                    "artist": artist,
                    "lyrics": lyrics,
                    "score": score_notes,
                },
            )

            # 8) harmony(키/카포/코드) 추정
            beats_per_bar = max(1, int(time_signature_numerator))
            total_bars = int(math.ceil(max(1, len(beat_times)) / beats_per_bar))

            # bar start 기준 정렬(beat_times[0]를 0초로 가정)
            start_t = float(beat_times[0]) if beat_times else 0.0
            rel_notes: List[NoteEvent] = []
            for ev in notes:
                rs = float(ev.start) - start_t
                re = float(ev.end) - start_t
                if re <= 0:
                    continue
                if rs >= target_seconds:
                    continue
                rel_notes.append(NoteEvent(string=ev.string, fret=ev.fret, start=rs, end=re))

            harmony = await asyncio.to_thread(
                analyze_harmony,
                rel_notes,
                tempo,
                time_signature_numerator=time_signature_numerator,
                max_bars=total_bars,
            )

            # stage=harmony: bar start에 chord 텍스트를 beat에 주입
            chords = harmony.chords
            chord_by_beat: List[str | None] = [None for _ in beat_times]
            for bar_idx in range(min(total_bars, len(chords))):
                bar_start_beat = bar_idx * beats_per_bar
                if 0 <= bar_start_beat < len(beat_times):
                    chord_by_beat[bar_start_beat] = chords[bar_idx]

            score_harmony = beats_to_alphatab_score(
                beat_times,
                title=title,
                tempo=tempo,
                time_signature_numerator=time_signature_numerator,
                key=harmony.key,
                capo=harmony.capo,
                chords=chords,
                notes_by_beat=notes_by_beat,
                lyrics_by_beat=lyrics_by_beat,
                chord_by_beat=chord_by_beat,
            )
            yield send_event(
                "message",
                {
                    "stage": "harmony",
                    "progress": 95,
                    "title": title,
                    "artist": artist,
                    "lyrics": lyrics,
                    "score": score_harmony,
                },
            )

            yield send_event(
                "message",
                {
                    "stage": "done",
                    "progress": 100,
                    "title": title,
                    "artist": artist,
                    "lyrics": lyrics,
                    "score": score_harmony,
                },
            )
        except Exception as e:
            yield send_event(
                "message",
                {
                    "stage": "error",
                    "progress": 0,
                    "detail": str(e),
                },
            )

    return StreamingResponse(event_gen(), media_type="text/event-stream")

