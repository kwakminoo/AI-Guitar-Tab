"""
기타 스템 onset 추출 및 MIDI 16분음표 그리드 스냅.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pretty_midi


def snap_midi_notes_to_sixteenth_grid(
    midi: pretty_midi.PrettyMIDI,
    bpm: float,
    beat_times_sec: list[float],
) -> None:
    """노트 시작을 (첫 박 기준) 1/16 노트 길이 그리드에 스냅. 종료는 길이 유지."""
    bpm = max(20.0, min(300.0, float(bpm)))
    quarter_sec = 60.0 / bpm
    sixteenth = quarter_sec / 4.0
    t_anchor = float(beat_times_sec[0]) if beat_times_sec else 0.0

    for inst in midi.instruments:
        if inst.is_drum:
            continue
        for note in inst.notes:
            rel = float(note.start) - t_anchor
            k = round(rel / sixteenth)
            new_start = max(0.0, t_anchor + k * sixteenth)
            dur = max(1e-3, float(note.end) - float(note.start))
            note.start = new_start
            note.end = new_start + dur


def analyze_onsets_from_guitar_audio(
    audio_path: Path,
    *,
    max_duration_sec: float = 600.0,
    bpm_hint: float | None = None,
) -> dict[str, Any]:
    """
    기타 stem 오디오에서 onset 시각(초)을 추출한다.
    반환: ok, onset_times_sec, sr, error(optional)
    """
    out: dict[str, Any] = {
        "ok": False,
        "onset_times_sec": [],
        "sr": None,
        "error": None,
    }
    try:
        import librosa
    except ImportError as e:
        out["error"] = f"librosa_import:{e}"
        return out

    path = Path(audio_path)
    if not path.is_file():
        out["error"] = "file_not_found"
        return out

    try:
        y, sr = librosa.load(
            str(path),
            sr=22050,
            mono=True,
            duration=max_duration_sec,
        )
    except Exception as e:
        out["error"] = f"load:{e}"
        return out

    if y.size < sr * 0.5:
        out["error"] = "audio_too_short"
        return out

    try:
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_env,
            sr=sr,
            hop_length=512,
            units="frames",
            backtrack=False,
            pre_max=20,
            post_max=20,
            pre_avg=100,
            post_avg=100,
            delta=0.2,
            wait=1,
        )
        onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=512)
        onset_times_sec = sorted(set(round(float(t), 6) for t in np.atleast_1d(onset_times).tolist()))
        if len(onset_times_sec) < 2:
            out["error"] = "onsets_too_few"
            return out
        out["ok"] = True
        out["onset_times_sec"] = onset_times_sec
        out["sr"] = int(sr)
    except Exception as e:
        out["error"] = f"onset_detect:{e}"
        return out

    return out
