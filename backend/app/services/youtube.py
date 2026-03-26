from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from urllib.request import urlopen, Request
from difflib import SequenceMatcher

from yt_dlp import YoutubeDL


def download_audio_from_youtube(
    url: str,
    output_dir: Path,
    audio_format: Literal["wav", "mp3", "flac"] = "wav",
    max_seconds: int | None = None,
) -> Path:
    """
    유튜브 URL에서 오디오를 다운로드하여 지정한 폴더에 저장하고 경로를 반환한다.
    - ffmpeg/ffprobe가 PATH에 있어야 한다.
    - 또는 환경변수 FFMPEG_LOCATION에 ffmpeg/ffprobe가 있는 폴더 경로를 지정할 수 있다.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_location = os.getenv("FFMPEG_LOCATION")
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None
    if not (ffmpeg_ok and ffprobe_ok) and not ffmpeg_location:
        raise RuntimeError(
            "ffmpeg/ffprobe를 찾을 수 없습니다. ffmpeg를 설치해 PATH에 추가하거나, "
            "환경변수 FFMPEG_LOCATION에 ffmpeg.exe/ffprobe.exe가 있는 폴더 경로를 지정해 주세요."
        )

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        **({"ffmpeg_location": ffmpeg_location} if ffmpeg_location else {}),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "0",
            }
        ],
    }

    # max_seconds이 주어지면, 다운로드 후 ffmpeg로 앞부분만 잘라 사용한다.
    # (yt-dlp의 download_ranges는 환경/포맷에 따라 동작이 불안정할 수 있어 기본은 보수적으로 유지)

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # postprocessor가 만든 최종 파일 이름을 구성
        video_id = info.get("id")
        filename = output_dir / f"{video_id}.{audio_format}"

    if not filename.exists():
        raise FileNotFoundError(f"다운로드된 오디오 파일을 찾을 수 없습니다: {filename}")

    if max_seconds is not None and max_seconds > 0:
        trimmed = output_dir / f"{video_id}_trimmed.{audio_format}"
        ffmpeg_bin = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        ffmpeg_location = os.getenv("FFMPEG_LOCATION")
        ffmpeg_cmd = ffmpeg_bin
        if ffmpeg_location:
            candidate = Path(ffmpeg_location) / ffmpeg_bin
            if candidate.exists():
                ffmpeg_cmd = str(candidate)

        import subprocess

        subprocess.run(
            [
                ffmpeg_cmd,
                "-y",
                "-i",
                str(filename),
                "-t",
                str(max_seconds),
                str(trimmed),
            ],
            check=True,
        )
        if trimmed.exists():
            return trimmed

    return filename


def fetch_youtube_basic_meta(url: str) -> dict:
    """
    유튜브 링크에서 제목/아티스트(업로더) 정도의 가벼운 메타를 가져온다.
    """
    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    video_title = str(info.get("title") or info.get("track") or "Unknown Title")
    title = str(info.get("track") or video_title)
    artist = str(
        info.get("artist")
        or info.get("uploader")
        or info.get("channel")
        or "Unknown Artist"
    )
    return {"video_title": video_title, "title": title, "artist": artist}


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _lrclib_search_lyrics(query: str) -> list[dict]:
    try:
        url = f"https://lrclib.net/api/search?q={quote(query)}"
        req = Request(url, headers={"User-Agent": "AI-Guitar-Tab/1.0"})
        with urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if isinstance(payload, list):
            return payload
        return []
    except Exception:
        return []


def _lrclib_fetch_lyrics_by_id(lyrics_id: int) -> str | None:
    try:
        url = f"https://lrclib.net/api/get/{lyrics_id}"
        req = Request(url, headers={"User-Agent": "AI-Guitar-Tab/1.0"})
        with urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        lyrics = payload.get("syncedLyrics") or payload.get("plainLyrics")
        if isinstance(lyrics, str) and lyrics.strip():
            return lyrics.strip()
        return None
    except Exception:
        return None


def infer_song_meta_from_video_title(
    video_title: str,
    *,
    fallback_artist: str | None = None,
) -> dict:
    """
    유튜브 video title만으로 LRCLIB에서 곡/가수를 검색하고 가사를 가져온다.
    - 정확도 최우선: search 결과 중 video_title과 가장 유사한 항목을 선택한다.
    - 결과가 없으면 fallback(영상 title, fallback_artist)를 사용한다.
    """
    video_title = (video_title or "").strip()
    if not video_title:
        return {"title": "Unknown Title", "artist": fallback_artist or "Unknown Artist", "lyrics": None}

    # LRCLIB 검색은 (q=) 형태가 가장 범용적이다.
    results = _lrclib_search_lyrics(video_title)
    if not results:
        return {"title": video_title, "artist": fallback_artist or "Unknown Artist", "lyrics": None}

    best = None
    best_score = -1.0
    for r in results:
        track_name = str(r.get("trackName") or "")
        artist_name = str(r.get("artistName") or "")
        if not track_name and not artist_name:
            continue

        candidate = f"{track_name} {artist_name}".strip()
        score = _similarity(video_title, candidate)
        # “Artist - Song” 같은 형태가 포함된 경우 가산점
        if " - " in video_title or "–" in video_title or "—" in video_title:
            if _similarity(video_title.split(" - ", 1)[-1], track_name) > 0.6:
                score += 0.1

        if score > best_score:
            best_score = score
            best = r

    if not best:
        return {"title": video_title, "artist": fallback_artist or "Unknown Artist", "lyrics": None}

    chosen_title = str(best.get("trackName") or video_title)
    chosen_artist = str(best.get("artistName") or fallback_artist or "Unknown Artist")
    lyrics_id = best.get("id")
    lyrics = _lrclib_fetch_lyrics_by_id(int(lyrics_id)) if isinstance(lyrics_id, int) else None
    return {"title": chosen_title, "artist": chosen_artist, "lyrics": lyrics}


def fetch_lyrics_lightweight(artist: str, title: str) -> str | None:
    """
    가벼운 공개 API(LRCLIB)로 가사를 시도해서 가져온다.
    실패해도 None 반환(분석 파이프라인에 영향 주지 않음).
    """
    try:
        q_title = quote(title)
        q_artist = quote(artist)
        url = f"https://lrclib.net/api/get?track_name={q_title}&artist_name={q_artist}"
        req = Request(url, headers={"User-Agent": "AI-Guitar-Tab/1.0"})
        with urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        # syncedLyrics(LRC 타임코드)가 있으면 그걸 우선으로 사용한다.
        lyrics = payload.get("syncedLyrics") or payload.get("plainLyrics")
        if isinstance(lyrics, str) and lyrics.strip():
            return lyrics.strip()
        return None
    except Exception:
        return None

