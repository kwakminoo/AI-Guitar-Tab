from __future__ import annotations

import re
from typing import List, Tuple


_LRC_TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?\]")


def strip_lyrics_markup(text: str) -> str:
    # GuitarPro/릴릭스에서 흔히 등장하는 태그/메타를 최대한 제거
    # (정확 문법 보장보단 “렌더에 방해되는 부분”을 줄이는 목적)
    text = re.sub(r"\[[^\]]*\]", " ", text)  # [Chorus], [Verse], ...
    text = re.sub(r"<[^>]+>", " ", text)  # <i>...</i>
    text = text.replace("&amp;", "&")
    return text


def parse_lrc(lyrics: str) -> List[Tuple[float, str]]:
    """
    LRC 형식에서 (time_sec, text)를 추출한다.
    - 한 줄에 타임스탬프가 여러 개 있을 수 있으므로 각각에 동일 text를 매핑한다.
    """
    if not lyrics:
        return []

    events: List[Tuple[float, str]] = []
    for raw_line in lyrics.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        matches = list(_LRC_TIMESTAMP_RE.finditer(line))
        if not matches:
            continue

        # 타임스탬프 제거 후 남은 텍스트 사용
        text = _LRC_TIMESTAMP_RE.sub("", line).strip()
        text = strip_lyrics_markup(text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue

        for m in matches:
            mm = int(m.group(1))
            ss = int(m.group(2))
            frac = m.group(3) or "0"
            # .xx -> ms로 취급 (0.5 => 50ms 근사)
            ms = int(frac.ljust(2, "0")[:2])
            t = mm * 60 + ss + ms / 100.0
            events.append((t, text))

    events.sort(key=lambda x: x[0])
    return events


def _beat_index_nearest(beat_times: List[float], t: float) -> int | None:
    if not beat_times:
        return None
    if t < beat_times[0] or t > beat_times[-1]:
        return None

    # 선형 탐색보단 간단한 이진 검색
    lo, hi = 0, len(beat_times) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if beat_times[mid] < t:
            lo = mid + 1
        else:
            hi = mid
    # lo==hi 인접 두 점 중 가까운 쪽 선택
    idx2 = lo
    idx1 = max(0, idx2 - 1)
    if idx1 == idx2:
        return idx1
    return idx1 if abs(beat_times[idx1] - t) <= abs(beat_times[idx2] - t) else idx2


def map_lyrics_to_beats(lyrics: str | None, beat_times: List[float]) -> List[str | None]:
    """
    beat grid에 lyrics를 매핑한다.
    - syncedLyrics(LRC 타임코드)가 포함되면 해당 time을 nearest beat에 매핑
    - 타임코드가 없으면 가사 토큰을 beat에 균등 분배(휴리스틱)
    """
    beat_lyrics: List[str | None] = [None for _ in beat_times]
    if not lyrics:
        return beat_lyrics

    cleaned = strip_lyrics_markup(lyrics)
    if _LRC_TIMESTAMP_RE.search(cleaned):
        events = parse_lrc(cleaned)
        for t, text in events:
            idx = _beat_index_nearest(beat_times, t)
            if idx is None:
                continue

            # “타이트”를 위해 한 이벤트 텍스트를 beat 여러 칸에 분산
            if re.search(r"\s+", text):
                tokens = [tok for tok in re.split(r"\s+", text) if tok]
                joiner = " "
            else:
                # 공백 없는 경우는 글자 단위로 쪼개되, 너무 길면 한 덩어리로 둔다.
                chars = [c for c in text if c.strip()]
                tokens = chars if len(chars) <= 12 else [text]
                joiner = ""

            for j, tok in enumerate(tokens):
                bi = idx + j
                if bi >= len(beat_times):
                    break
                if beat_lyrics[bi] is None:
                    beat_lyrics[bi] = tok
                else:
                    beat_lyrics[bi] = f"{beat_lyrics[bi]}{joiner}{tok}" if joiner else f"{beat_lyrics[bi]}{tok}"

        return beat_lyrics

    # -------- 타임코드가 없는 경우: beat grid 균등 분배 --------
    # 라인 단위/단어 단위를 beat에 분산(정확도는 timecode 기반보다 떨어짐)
    normalized = re.sub(r"\s+", " ", cleaned).strip()
    if not normalized:
        return beat_lyrics

    if re.search(r"\s+", normalized):
        tokens = [tok for tok in re.split(r"\s+", normalized) if tok]
        joiner = " "
    else:
        chars = [c for c in normalized if c.strip()]
        tokens = chars if len(chars) <= 64 else [normalized]
        joiner = ""

    if not tokens:
        return beat_lyrics

    n_beats = len(beat_times)
    for i, tok in enumerate(tokens):
        bi = int(i * n_beats / max(1, len(tokens)))
        bi = min(n_beats - 1, max(0, bi))
        if beat_lyrics[bi] is None:
            beat_lyrics[bi] = tok
        else:
            beat_lyrics[bi] = f"{beat_lyrics[bi]}{joiner}{tok}" if joiner else f"{beat_lyrics[bi]}{tok}"

    return beat_lyrics

