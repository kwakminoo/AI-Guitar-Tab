"""
MIDI 노트를 1/16 그리드에 스냅(옵션). BPM·박 앵커는 호출부에서 제공한다.
"""

from __future__ import annotations

from typing import Any

import pretty_midi


def snap_midi_notes_to_sixteenth_grid(
    midi: pretty_midi.PrettyMIDI,
    bpm: float,
    beat_times_sec: list[float],
    *,
    enabled: bool = False,
    max_snap_error_sec: float = 0.03,
    snap_note_end: bool = False,
    stats_out: dict[str, Any] | None = None,
) -> None:
    """조건부로 노트 시작을 1/16 그리드에 스냅한다."""
    if stats_out is not None:
        stats_out.setdefault("snapped_note_count", 0)
    if not enabled:
        return
    bpm = max(20.0, min(300.0, float(bpm)))
    quarter_sec = 60.0 / bpm
    sixteenth = quarter_sec / 4.0
    t_anchor = float(beat_times_sec[0]) if beat_times_sec else 0.0
    max_error = max(0.0, float(max_snap_error_sec))
    snapped_count = 0

    for inst in midi.instruments:
        if inst.is_drum:
            continue
        for note in inst.notes:
            rel = float(note.start) - t_anchor
            k = round(rel / sixteenth)
            new_start = max(0.0, t_anchor + k * sixteenth)
            snap_error = abs(new_start - float(note.start))
            if snap_error > max_error:
                continue
            dur = max(1e-3, float(note.end) - float(note.start))
            note.start = new_start
            if snap_note_end:
                rel_end = float(note.end) - t_anchor
                k_end = round(rel_end / sixteenth)
                new_end = max(note.start + 1e-3, t_anchor + k_end * sixteenth)
                note.end = new_end
            else:
                note.end = new_start + dur
            snapped_count += 1
    if stats_out is not None:
        stats_out["snapped_note_count"] = int(snapped_count)
