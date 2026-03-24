from __future__ import annotations

import math
from typing import List, Tuple

import librosa
import numpy as np


def estimate_tempo_and_meter(
    audio_path: str,
    *,
    target_seconds: float = 30.0,
    candidate_numerators: Tuple[int, ...] = (2, 3, 4, 5, 6),
) -> Tuple[int, int, List[float]]:
    """
    - tempo(BPM): librosa beat_track 결과 사용
    - time_signature_numerator: beat strength로부터 간단한 다운비트/바 스코어링
    - beat_times: 추정된 바 시작(다운비트)부터 target_seconds 범위 내 beat times만 반환
    """
    y, sr = librosa.load(audio_path, sr=None, mono=True, duration=target_seconds)
    if y.size == 0:
        # 입력이 비정상인 경우 fallback
        default_tempo = 90
        beat_period = 60.0 / default_tempo
        n_beats = max(1, int(math.ceil(target_seconds / beat_period)))
        beat_times = [i * beat_period for i in range(n_beats)]
        return default_tempo, 4, beat_times

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    # beat_track 기본은 frames 기반
    if beat_frames is None or len(beat_frames) == 0:
        default_tempo = 90
        beat_period = 60.0 / default_tempo
        n_beats = max(1, int(math.ceil(target_seconds / beat_period)))
        beat_times = [i * beat_period for i in range(n_beats)]
        return default_tempo, 4, beat_times

    beat_times = librosa.frames_to_time(beat_frames, sr=sr).astype(float).tolist()
    if not beat_times:
        default_tempo = 90
        beat_period = 60.0 / default_tempo
        n_beats = max(1, int(math.ceil(target_seconds / beat_period)))
        beat_times = [i * beat_period for i in range(n_beats)]
        return default_tempo, 4, beat_times

    beat_strength = librosa.onset.onset_strength(y=y, sr=sr).astype(float)
    # onset_strength 시계열을 beat time으로 샘플링 (nearest/interp)
    hop_length = 512
    onset_times = librosa.frames_to_time(np.arange(len(beat_strength)), sr=sr, hop_length=hop_length)
    beat_strength_at_beats = np.interp(np.array(beat_times), onset_times, beat_strength).astype(float)

    best_n = 4
    best_offset = 0
    best_score = -1.0

    beat_indices = np.arange(len(beat_times))
    for n in candidate_numerators:
        if n <= 0:
            continue
        for offset in range(n):
            mask = (beat_indices % n) == offset
            score = float(beat_strength_at_beats[mask].sum())
            if score > best_score:
                best_score = score
                best_n = int(n)
                best_offset = int(offset)

    # best_offset에 해당하는 첫 beat을 바 시작(다운비트)로 잡는다.
    first_bar_beat_idx = 0
    for i in range(len(beat_times)):
        if (i % best_n) == best_offset:
            first_bar_beat_idx = i
            break

    trimmed = beat_times[first_bar_beat_idx:]
    if not trimmed:
        trimmed = beat_times
        first_bar_beat_idx = 0

    start_t = trimmed[0]
    end_t = start_t + float(target_seconds)
    trimmed = [t for t in trimmed if t <= end_t]

    tempo_int = int(max(30, min(220, round(float(tempo) if tempo else 90))))
    if len(trimmed) < best_n:
        # beat_track이 너무 적게 잡혔으면 평균 beat_period로 보강
        beat_period = 60.0 / max(1, tempo_int)
        while len(trimmed) < best_n:
            trimmed.append(trimmed[-1] + beat_period)

    return tempo_int, best_n, trimmed

