"""
LRCLIB (https://lrclib.net) API로 가사 조회·캐시.
API 문서: https://lrclib.net/docs — User-Agent 권장사항 준수.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

LRCLIB_BASE = "https://lrclib.net"
USER_AGENT = "AI-Guitar-Tab/1.0 (https://github.com/)"
REQUEST_TIMEOUT_SEC = 25


def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def normalize_artist_for_search(artist: str | None, uploader: str | None) -> str:
    """아티스트: track artist 우선, 없으면 채널명(uploader)."""
    raw = (artist or uploader or "").strip()
    if not raw:
        return ""
    # YouTube Music "Artist - Topic" 형태
    raw = re.sub(r"\s*-\s*Topic\s*$", "", raw, flags=re.I).strip()
    return raw


def parse_artist_and_track_from_youtube_title(title: str) -> tuple[str | None, str | None]:
    """
    유튜브 음원 영상 흔한 형식: '아티스트 - 곡명 / 영문제목 / …' 의 첫 구간에서 아티스트·곡명 추출.
    예: '검정치마 - 기다린 만큼, 더 / The Black Skirts - Wait More (OST) / 가사'
    """
    t = (title or "").strip()
    if not t:
        return None, None
    t = re.sub(r"\s*/\s*가사\s*$", "", t, flags=re.I).strip()
    first = t.split("/")[0].strip()
    if " - " not in first:
        return None, None
    left, right = first.split(" - ", 1)
    left, right = left.strip(), right.strip()
    if len(left) < 2 or len(right) < 2:
        return None, None
    return left, right


def normalize_title_for_search(title: str) -> str:
    """
    괄호 안 부제·라이브 표기 등을 제거해 검색 적중률을 올린다.
    예: '너드커넥션 (Nerd Connection) 좋은 밤 좋은 꿈 (취중 Live)' → 앞부분 보존 시도.
    """
    t = (title or "").strip()
    if not t:
        return ""
    # 반복적으로 (…) 세그먼트 제거 — 너무 짧아지면 중단
    prev = None
    for _ in range(12):
        prev = t
        t = re.sub(r"\s*\([^)]{0,200}\)\s*", " ", t).strip()
        if t == prev:
            break
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _strip_synced_lyrics_to_plain(synced: str) -> str:
    """[mm:ss.xx] 또는 [mm:ss] 태그 제거."""
    if not synced:
        return ""
    lines = []
    for line in synced.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"^\[[\d:.]+\]\s*", "", line)
        lines.append(line)
    return "\n".join(lines).strip()


def _pick_best_track(records: list[dict[str, Any]], duration_sec: float | None) -> dict[str, Any] | None:
    if not records:
        return None
    scored: list[tuple[float, dict[str, Any]]] = []
    for r in records:
        plain = (r.get("plainLyrics") or "").strip()
        synced = (r.get("syncedLyrics") or "").strip()
        text = plain or _strip_synced_lyrics_to_plain(synced)
        if not text:
            continue
        if r.get("instrumental") is True and not text:
            continue
        dur = r.get("duration")
        score = 0.0
        if duration_sec is not None and dur is not None:
            try:
                diff = abs(float(dur) - float(duration_sec))
            except (TypeError, ValueError):
                diff = 999.0
            # 짧은 길이 차이일수록 우선 (LRCLIB 문서: ±2초 권장 — 여기서는 후보 정렬용으로 완화)
            score -= min(diff, 120.0) * 2.0
        scored.append((score, r))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def fetch_lyrics_from_lrclib(
    title: str,
    artist: str | None,
    uploader: str | None,
    duration_sec: float | None,
    *,
    cache_dir: Path | None = None,
) -> tuple[str | None, str]:
    """
    LRCLIB에서 가사 조회. (lyrics, source) source는 'lrclib' | 'none'.
    cache_dir가 있으면 성공 시 텍스트 캐시.
    """
    parsed_artist, parsed_track = parse_artist_and_track_from_youtube_title(title)

    artist_q = normalize_artist_for_search(artist, uploader)
    title_norm = normalize_title_for_search(title)

    # 메타에 아티스트가 없을 때: 제목의 '가수 - 곡명'을 우선 (업로더가 음반사인 경우가 많음)
    if parsed_artist and parsed_track and not (artist and artist.strip()):
        artist_q = parsed_artist
        title_norm = normalize_title_for_search(parsed_track)

    if not title_norm or not artist_q:
        return None, "none"

    cache_key = hashlib.sha256(f"{title_norm.lower()}|{artist_q.lower()}".encode("utf-8")).hexdigest()
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                ly = cached.get("lyrics")
                if isinstance(ly, str) and ly.strip():
                    return ly.strip(), "lrclib_cache"
            except Exception:
                pass

    params_list: list[dict[str, str]] = [
        {"track_name": title_norm, "artist_name": artist_q},
    ]
    # 짧은 제목 후보 (한글 곡명만 남은 경우 등)
    short = re.sub(r"^[^\s]+\s+", "", title_norm, count=1).strip()
    if short and short != title_norm and len(short) >= 2:
        params_list.append({"track_name": short, "artist_name": artist_q})

    # '/' 뒤 영문·다국어 세그먼트 (예: 'The Black Skirts - Wait More (OST)')
    for seg in title.split("/")[1:]:
        seg = seg.strip()
        if not seg or seg.lower() == "가사":
            continue
        seg_n = normalize_title_for_search(seg)
        if " - " not in seg_n:
            continue
        ea, et = seg_n.split(" - ", 1)
        ea, et = ea.strip(), et.strip()
        if len(ea) >= 2 and len(et) >= 2:
            params_list.append({"track_name": normalize_title_for_search(et), "artist_name": ea})

    records: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    def _merge_results(data: Any) -> None:
        if not isinstance(data, list):
            return
        for item in data:
            if not isinstance(item, dict):
                continue
            tid = item.get("id")
            try:
                iid = int(tid) if tid is not None else -1
            except (TypeError, ValueError):
                iid = -1
            if iid >= 0 and iid in seen_ids:
                continue
            if iid >= 0:
                seen_ids.add(iid)
            records.append(item)

    for params in params_list:
        qstr = urllib.parse.urlencode(params)
        url = f"{LRCLIB_BASE}/api/search?{qstr}"
        try:
            data = _http_get_json(url)
            _merge_results(data)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue

    # 보조: 키워드 검색
    q_kw = f"{title_norm} {artist_q}".strip()
    try:
        data = _http_get_json(f"{LRCLIB_BASE}/api/search?{urllib.parse.urlencode({'q': q_kw})}")
        _merge_results(data)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass

    best = _pick_best_track(records, duration_sec)
    if best is None:
        return None, "none"

    plain = (best.get("plainLyrics") or "").strip()
    synced = (best.get("syncedLyrics") or "").strip()
    text = plain or _strip_synced_lyrics_to_plain(synced)
    if not text:
        return None, "none"

    if cache_dir is not None:
        cache_file = cache_dir / f"{cache_key}.json"
        try:
            cache_file.write_text(
                json.dumps(
                    {"lyrics": text, "source": "lrclib", "lrclib_id": best.get("id")},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    return text, "lrclib"
