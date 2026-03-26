from __future__ import annotations

from typing import List, Dict, Any, Optional

from .transcribe import NoteEvent


def notes_to_alphatab_score(
    notes: List[NoteEvent],
    *,
    title: str,
    tempo: int = 90,
    key: str = "C major",
    capo: int = 0,
    chords: List[str] | None = None,
) -> Dict[str, Any]:
    """
    전사된 NoteEvent 리스트를 프론트엔드의 AlphaTabScore(JSON) 구조로 변환한다.
    - timeSignature는 기본 4/4로 고정.
    - 일단 모든 노트를 하나의 beat 리스트에 순차적으로 배치한다.
    """
    beats = []
    current_time = 0.0
    chords = chords or []
    for ev in notes:
        bar_duration = (60.0 / max(40, min(220, tempo))) * 4.0
        bar_idx = int(max(0.0, ev.start) // bar_duration)
        chord = chords[bar_idx] if 0 <= bar_idx < len(chords) else None
        beats.append(
            {
                "time": current_time,
                "chord": chord,
                "lyric": None,
                "notes": [
                    {
                        "string": ev.string,
                        "fret": ev.fret,
                        "start": ev.start,
                        "end": ev.end,
                    }
                ],
            }
        )
        current_time = ev.end

    score: Dict[str, Any] = {
        "version": 1,
        "meta": {
            "title": title,
            "tempo": tempo,
            "timeSignature": {"numerator": 4, "denominator": 4},
            "key": key,
            "capo": capo,
            "chords": chords,
        },
        "tracks": [
            {
                "name": "Guitar",
                "type": "guitar",
                "strings": 6,
                "tuning": [40, 45, 50, 55, 59, 64],
                "beats": beats,
            }
        ],
    }
    return score


def beats_to_alphatab_score(
    beat_times: List[float],
    *,
    title: str,
    tempo: int,
    time_signature_numerator: int,
    key: str = "C major",
    capo: int = 0,
    chords: List[str] | None = None,
    notes_by_beat: Dict[int, List[NoteEvent]] | None = None,
    lyrics_by_beat: List[str | None] | None = None,
    chord_by_beat: List[str | None] | None = None,
    technique_by_beat: List[str | None] | None = None,
) -> Dict[str, Any]:
    """
    beat grid(beat_times 길이) 기준으로 alphaTab 렌더용 JSON score를 만든다.
    - notes_by_beat: beat index -> NoteEvent 리스트
    - lyrics_by_beat: beat index -> lyric 텍스트
    - chord_by_beat: beat index -> chord 텍스트
    - technique_by_beat: beat index -> 주법(스트로크 등) 짧은 라벨
    """
    n = len(beat_times)
    notes_by_beat = notes_by_beat or {}
    lyrics_by_beat = lyrics_by_beat or [None for _ in range(n)]
    chord_by_beat = chord_by_beat or [None for _ in range(n)]
    technique_by_beat = technique_by_beat or [None for _ in range(n)]
    chords = chords or []

    beats: List[Dict[str, Any]] = []
    for i in range(n):
        beat_notes = notes_by_beat.get(i, [])
        lyric = lyrics_by_beat[i] if i < len(lyrics_by_beat) else None
        tech = technique_by_beat[i] if i < len(technique_by_beat) else None
        if lyric and tech:
            lyric = f"{lyric} {tech}"
        elif tech and not lyric:
            lyric = tech
        beats.append(
            {
                "time": float(beat_times[i]),
                "chord": chord_by_beat[i] if i < len(chord_by_beat) else None,
                "lyric": lyric,
                "notes": [
                    {
                        "string": int(ev.string),
                        "fret": int(ev.fret),
                        "start": float(ev.start),
                        "end": float(ev.end),
                    }
                    for ev in beat_notes
                ],
            }
        )

    return {
        "version": 1,
        "meta": {
            "title": title,
            "tempo": tempo,
            "timeSignature": {"numerator": int(time_signature_numerator), "denominator": 4},
            "key": key,
            "capo": int(capo),
            "chords": chords,
        },
        "tracks": [
            {
                "name": "Guitar",
                "type": "guitar",
                "strings": 6,
                "tuning": [40, 45, 50, 55, 59, 64],
                "beats": beats,
            }
        ],
    }

