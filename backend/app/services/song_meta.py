"""
유튜브 영상 제목을 원문 그대로 쓰지 않고,
정리한 뒤 Google Custom Search(선택) + LRCLIB로 곡명·가수·가사를 수집한다.

환경변수(선택, Google 검색 사용 시):
  GOOGLE_API_KEY  — Google Cloud API 키
  GOOGLE_CSE_ID   — Programmable Search Engine ID (검색엔진 ID)

키가 없으면 LRCLIB만으로 유사 검색(기존 infer_song_meta_from_video_title)한다.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .youtube import (
    fetch_lyrics_lightweight,
    infer_song_meta_from_video_title,
)


def clean_youtube_video_title(raw: str) -> str:
    """괄호 태그·Official/MV 등을 제거해 검색용 문자열로 만든다."""
    s = (raw or "").strip()
    if not s:
        return ""
    # [Official Video], (MV), [가사/Lyrics] 등
    s = re.sub(
        r"\s*[\[\(][^\]\)]{0,80}[\]\)]\s*",
        " ",
        s,
        flags=re.IGNORECASE,
    )
    # | 이후 채널명·사이트명
    s = s.split("|")[0].strip()
    # 끝부분 흔한 접미사
    s = re.sub(
        r"[\s\-–—|]*(?:official\s*)?(?:music\s*)?(?:video|audio|mv|lyrics|가사)\s*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _google_custom_search_items(query: str, *, num: int = 8) -> list[dict[str, Any]]:
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    cx = os.environ.get("GOOGLE_CSE_ID", "").strip()
    if not key or not cx:
        return []
    n = max(1, min(num, 10))
    url = (
        "https://www.googleapis.com/customsearch/v1"
        f"?key={quote(key)}&cx={quote(cx)}&q={quote(query)}&num={n}"
    )
    try:
        req = Request(url, headers={"User-Agent": "AI-Guitar-Tab/1.0"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("items")
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _pairs_from_google_result_title(line: str) -> list[tuple[str, str]]:
    """검색 결과 제목에서 (곡 제목, 가수) 후보를 뽑는다."""
    t = (line or "").strip()
    if not t:
        return []
    t = re.sub(r"\s*-\s*YouTube\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\|.*$", "", t)
    t = t.strip()

    out: list[tuple[str, str]] = []
    if " - " in t:
        parts = [p.strip() for p in t.split(" - ") if p.strip()]
        if len(parts) >= 2:
            a, b = parts[0], parts[-1]
            a = re.sub(r"\s*Lyrics\s*$", "", a, flags=re.IGNORECASE).strip()
            b = re.sub(r"\s*Lyrics\s*$", "", b, flags=re.IGNORECASE).strip()
            # 흔한 패턴: "곡 - 가수", "가수 - 곡"
            out.append((a, b))
            out.append((b, a))
    return out


def _unique_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for title, artist in pairs:
        title = title.strip()
        artist = artist.strip()
        if len(title) < 2 or len(artist) < 1:
            continue
        key = (title.lower(), artist.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((title, artist))
    return out


def resolve_song_metadata_from_video(
    video_title: str,
    *,
    fallback_artist: str | None = None,
) -> dict[str, Any]:
    """
    유튜브 영상 제목을 토대로 곡 제목·가수·가사를 수집한다.

    반환:
      title, artist, lyrics (LRCLIB 동기 가사), source, video_title_raw
    """
    raw = (video_title or "").strip()
    cleaned = clean_youtube_video_title(raw) or raw

    pairs: list[tuple[str, str]] = []
    google_items: list[dict[str, Any]] = []

    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    cx = os.environ.get("GOOGLE_CSE_ID", "").strip()
    if key and cx and cleaned:
        google_items = _google_custom_search_items(f"{cleaned} song lyrics", num=8)
        if not google_items:
            google_items = _google_custom_search_items(f"{cleaned} lyrics", num=8)
        for it in google_items:
            pairs.extend(_pairs_from_google_result_title(str(it.get("title") or "")))

    # 정리된 제목에서 "A - B" 패턴 (유튜브 흔한 형식)
    if " - " in cleaned:
        left, right = [x.strip() for x in cleaned.split(" - ", 1)]
        if left and right:
            pairs.insert(0, (right, left))
            pairs.insert(0, (left, right))

    pairs = _unique_pairs(pairs)

    for song_title, artist_name in pairs:
        lyrics = fetch_lyrics_lightweight(artist_name, song_title)
        if lyrics:
            return {
                "title": song_title,
                "artist": artist_name,
                "lyrics": lyrics,
                "source": "google_lrclib",
                "video_title_raw": raw,
            }

    # Google 첫 결과 제목 전체로 LRCLIB 유사 매칭 (제목 파싱만으로는 실패한 경우)
    if google_items:
        gt = str(google_items[0].get("title") or "").strip()
        gt = re.sub(r"\s*\|.*$", "", gt).strip()
        gt = re.sub(r"\s*-\s*YouTube\s*$", "", gt, flags=re.IGNORECASE).strip()
        if gt and len(gt) > 2:
            inferred_g = infer_song_meta_from_video_title(
                gt,
                fallback_artist=fallback_artist,
            )
            if inferred_g.get("lyrics"):
                return {
                    "title": str(inferred_g.get("title") or cleaned),
                    "artist": str(inferred_g.get("artist") or fallback_artist or "Unknown Artist"),
                    "lyrics": inferred_g.get("lyrics"),
                    "source": "google_title_lrclib",
                    "video_title_raw": raw,
                }

    # LRCLIB 유사도 검색(정리된 영상 제목 기준, 원문 그대로 아님)
    inferred = infer_song_meta_from_video_title(
        cleaned,
        fallback_artist=fallback_artist,
    )
    return {
        "title": str(inferred.get("title") or cleaned or "Unknown Title"),
        "artist": str(inferred.get("artist") or fallback_artist or "Unknown Artist"),
        "lyrics": inferred.get("lyrics"),
        "source": "lrclib",
        "video_title_raw": raw,
    }
