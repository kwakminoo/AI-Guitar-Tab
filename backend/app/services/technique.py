from __future__ import annotations

from typing import Dict, List

from .transcribe import NoteEvent


def estimate_strum_direction_by_beat(
    notes_by_beat: Dict[int, List[NoteEvent]],
    *,
    beat_count: int,
) -> List[str | None]:
    """
    비트마다 전사된 음들의 시작 시점을 기준으로,
    현이 낮은 번호(1) -> 높은 번호(6) 방향이면 Up, 반대면 Down으로 라벨링한다.

    - Dn: low E(6) 쪽에서 high E(1) 쪽으로 먼저 울리는 패턴
    - Up: high E(1) 쪽에서 low E(6) 쪽으로 먼저 울리는 패턴
    """
    out: List[str | None] = [None for _ in range(beat_count)]

    for beat_idx in range(beat_count):
        events = notes_by_beat.get(beat_idx, [])
        if len(events) < 2:
            continue

        sorted_events = sorted(events, key=lambda ev: (ev.start + ev.end) / 2.0)
        first = sorted_events[0]
        last = sorted_events[-1]
        if first.string == last.string:
            continue

        out[beat_idx] = "Dn" if first.string > last.string else "Up"

    return out

