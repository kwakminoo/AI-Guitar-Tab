"""
풀 믹스 오디오에서 BPM·박 시각을 추정하고, MIDI 노트를 1/16 그리드에 스냅한다.
1차: librosa.beat.beat_track (실패 시 상위에서 MIDI 템포 폴백).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pretty_midi


def analyze_beats_from_mix_mp3(mp3_path: Path, *, max_duration_sec: float = 600.0) -> dict[str, Any]:
    """
    mp3_path: 풀 믹스(또는 드럼이 있는 스템) 권장.
    반환: ok, bpm, beat_times_sec, downbeat_indices, sr, error(optional)
    """
    out: dict[str, Any] = {
        "ok": False,
        "bpm": None,
        "beat_times_sec": [],
        "downbeat_indices": [],
        "sr": None,
        "error": None,
    }
    try:
        import librosa
    except ImportError as e:
        out["error"] = f"librosa_import:{e}"
        return out

    path = Path(mp3_path)
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
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, hop_length=512)
        tempo_arr = np.atleast_1d(np.asarray(tempo, dtype=np.float64)).flatten()
        bpm = float(np.median(tempo_arr)) if tempo_arr.size > 0 else 120.0
        if not np.isfinite(bpm) or bpm <= 0:
            bpm = 120.0
        bpm = max(40.0, min(240.0, bpm))
        beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=512)
        beat_times_sec = [float(x) for x in np.atleast_1d(beat_times).tolist()]
        beat_times_sec = sorted(set(round(t, 6) for t in beat_times_sec))
        if len(beat_times_sec) < 2:
            out["error"] = "beats_too_few"
            return out
        # 4/4 가정: 매 4박을 다운비트로 표시(휴리스틱)
        downbeat_indices = [i for i in range(len(beat_times_sec)) if i % 4 == 0]
        out["ok"] = True
        out["bpm"] = bpm
        out["beat_times_sec"] = beat_times_sec
        out["downbeat_indices"] = downbeat_indices
        out["sr"] = int(sr)
    except Exception as e:
        out["error"] = f"beat_track:{e}"
        return out

    return out


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
