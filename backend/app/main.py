import asyncio
import hashlib
import math
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

from .services.alphatab_mapper import beats_to_alphatab_score
from .services.harmony import analyze_harmony
from .services.lyrics import map_lyrics_to_beats
from .services.musicxml import build_musicxml_from_beats, parse_musicxml_to_notes_by_beat
from .services.rhythm import estimate_tempo_and_meter
from .services.separate import extract_guitar_stem
from .services.transcribe import NoteEvent, transcribe_guitar_to_notes
from .services.technique import estimate_strum_direction_by_beat
from .services.song_meta import resolve_song_metadata_from_video
from .services.youtube import (
    download_audio_from_youtube,
    fetch_youtube_basic_meta,
)

app = FastAPI(title="AI Guitar Tab Backend")

# 직접 백엔드(8000)에 붙는 클라이언트·도구용 (프론트는 Next 리라이트로 동일 출처 권장)
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


class YoutubeTabPreviewResponse(BaseModel):
    """유튜브 URL → 메타·가사 + 오디오 분석으로 타브 점수."""

    title: str
    artist: str
    lyrics: str | None = None
    musicxml: str | None = None
    score: AlphaTabScore


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
            resolve_song_metadata_from_video,
            meta.get("video_title") or meta.get("title") or "",
            fallback_artist=meta.get("artist"),
        )
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


def _run_youtube_tab_analysis(url: str) -> dict:
    """
    유튜브에서 짧은 구간 오디오를 받아 리듬 추정 → 기타 전사 → 하모니 → AlphaTabScore.
    """
    target_seconds = 30.0
    job_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    work_dir = Path("data") / "jobs" / job_hash
    work_dir.mkdir(parents=True, exist_ok=True)

    meta = fetch_youtube_basic_meta(url)
    inferred = resolve_song_metadata_from_video(
        meta.get("video_title") or meta.get("title") or "",
        fallback_artist=meta.get("artist"),
    )
    title = str(inferred.get("title") or "Unknown Title")
    artist = str(inferred.get("artist") or "Unknown Artist")
    lyrics = inferred.get("lyrics")

    audio_path = download_audio_from_youtube(
        url,
        work_dir / "audio",
        "wav",
        int(target_seconds),
    )

    tempo, time_sig_num, beat_times = estimate_tempo_and_meter(
        str(audio_path),
        target_seconds=target_seconds,
    )

    lyrics_by_beat = map_lyrics_to_beats(lyrics, beat_times)

    guitar_stem = extract_guitar_stem(Path(audio_path), work_dir / "stems")
    notes = transcribe_guitar_to_notes(guitar_stem)

    notes_by_beat: Dict[int, List[NoteEvent]] = {}
    for ev in notes:
        mid = (float(ev.start) + float(ev.end)) / 2.0
        if not beat_times:
            continue
        if mid < beat_times[0] or mid > beat_times[-1]:
            continue
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

    technique_by_beat = estimate_strum_direction_by_beat(
        notes_by_beat,
        beat_count=len(beat_times),
    )

    beats_per_bar = max(1, int(time_sig_num))
    total_bars = int(math.ceil(max(1, len(beat_times)) / beats_per_bar))

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

    harmony = analyze_harmony(
        rel_notes,
        tempo,
        time_signature_numerator=time_sig_num,
        max_bars=total_bars,
    )

    chords = harmony.chords
    chord_by_beat: List[str | None] = [None for _ in beat_times]
    for bar_idx in range(min(total_bars, len(chords))):
        bar_start_beat = bar_idx * beats_per_bar
        if 0 <= bar_start_beat < len(beat_times):
            chord_by_beat[bar_start_beat] = chords[bar_idx]

    musicxml = build_musicxml_from_beats(
        beat_times,
        notes_by_beat,
        title=title,
        artist=artist,
        tempo=tempo,
        time_signature_numerator=time_sig_num,
    )
    musicxml_path = work_dir / "musicxml" / "preview.musicxml"
    musicxml_path.parent.mkdir(parents=True, exist_ok=True)
    musicxml_path.write_text(musicxml, encoding="utf-8")

    parsed_xml = parse_musicxml_to_notes_by_beat(musicxml)

    score_dict = beats_to_alphatab_score(
        beat_times,
        title=title,
        tempo=parsed_xml.tempo,
        time_signature_numerator=time_sig_num,
        key=harmony.key,
        capo=harmony.capo,
        chords=chords,
        notes_by_beat=parsed_xml.notes_by_beat,
        lyrics_by_beat=lyrics_by_beat,
        chord_by_beat=chord_by_beat,
        technique_by_beat=technique_by_beat,
    )
    return {
        "title": title,
        "artist": artist,
        "lyrics": lyrics,
        "musicxml": musicxml,
        "score": score_dict,
    }


@app.post("/api/youtube/tab-preview", response_model=YoutubeTabPreviewResponse)
async def youtube_tab_preview(payload: FromYoutubeRequest) -> YoutubeTabPreviewResponse:
    """
    유튜브 영상 링크 → (곡명·가수·가사 LRCLIB) + 앞부분 오디오 분석으로 타브 악보 JSON 생성.
    """
    url = str(payload.url)
    if "youtube.com" not in url and "youtu.be" not in url:
        raise HTTPException(status_code=400, detail="지원하지 않는 URL 형식입니다.")

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_youtube_tab_analysis, url),
            timeout=420.0,
        )
        return YoutubeTabPreviewResponse(
            title=result["title"],
            artist=result["artist"],
            lyrics=result["lyrics"],
            musicxml=result.get("musicxml"),
            score=AlphaTabScore(**result["score"]),
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="분석 시간이 제한(7분)을 초과했습니다. 다른 링크로 다시 시도해 주세요.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
