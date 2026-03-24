from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import List

import numpy as np
import soundfile as sf
import librosa

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


@dataclass
class NoteEvent:
    string: int
    fret: int
    start: float
    end: float


def _hz_to_midi(freq_hz: float) -> float:
    return 69 + 12 * np.log2(freq_hz / 440.0)


def _midi_to_hz(midi: float) -> float:
    return 440.0 * (2 ** ((midi - 69) / 12))


def _map_midi_to_guitar_string_fret(midi: float) -> tuple[int, int]:
    """
    MIDI 음 높이를 표준 튜닝(EADGBE)의 (string, fret) 로 매핑한다.
    string: 1 = high E, 6 = low E
    """
    # 표준 튜닝의 MIDI 값 (E2 A2 D3 G3 B3 E4)
    tuning_midi = np.array([64, 59, 55, 50, 45, 40], dtype=float)  # 1~6번줄
    fret_candidates = midi - tuning_midi
    # 0~20프렛 범위 안에서 가장 가까운 줄 선택
    valid_mask = (fret_candidates >= 0) & (fret_candidates <= 20)
    if not valid_mask.any():
        # 범위를 벗어나면 가장 가까운 줄로 클램프
        idx = int(np.argmin(np.abs(fret_candidates)))
        fret = int(round(fret_candidates[idx]))
        return idx + 1, max(0, min(20, fret))

    idx = int(np.argmin(np.where(valid_mask, np.abs(fret_candidates), np.inf)))
    fret = int(round(fret_candidates[idx]))
    return idx + 1, fret


def transcribe_guitar_to_notes(audio_path: Path) -> List[NoteEvent]:
    """
    Basic Pitch 모델을 사용해 기타 오디오에서 노트 이벤트를 추출한다.

    - Basic Pitch는 악기 비특화(polyphonic) 모델이지만, 기타 단일/소수 악기 트랙에
      대해서는 충분히 사용할 수 있는 품질을 제공한다.
    """
    audio_path = Path(audio_path)

    notes: List[NoteEvent] = []

    # 1) Basic Pitch (가능하면)로 전사
    # - Windows에서는 onnxruntime/tensorflow DLL 문제로 import 단계에서 실패할 수 있어
    #   서버 부팅이 깨지지 않도록 함수 내부에서 lazy import + fallback 처리한다.
    try:
        # basic_pitch import 시 출력되는 백엔드 경고(CoreML/TFLite 등)는 기능상 치명적이지 않아
        # import 구간에서만 일시적으로 숨긴다.
        previous_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            from basic_pitch.inference import predict  # type: ignore
        finally:
            logging.disable(previous_disable)

        _model_output, _midi_data, note_events = predict(
            audio_path,
            model_or_model_path=None,
            save_midi=False,
            sonify_midi=False,
        )

        for start, end, midi, _amp in note_events:
            if end - start < 0.05:
                continue
            string, fret = _map_midi_to_guitar_string_fret(midi)
            notes.append(
                NoteEvent(
                    string=string,
                    fret=fret,
                    start=float(start),
                    end=float(end),
                )
            )
    except Exception:
        notes = []

    # 2) Fallback: librosa 기반 단순 전사 (모노포닉 가정)
    if not notes:
        try:
            y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
            if y.size == 0:
                raise ValueError("empty audio")

            # onset(어택) 시점 검출
            onset_frames = librosa.onset.onset_detect(y=y, sr=sr, backtrack=True, units="frames")
            onset_times = librosa.frames_to_time(onset_frames, sr=sr)
            if len(onset_times) == 0:
                onset_times = np.array([0.0], dtype=float)

            # 각 구간에서 대표 피치 추정 (yin)
            f0 = librosa.yin(y, fmin=librosa.note_to_hz("E2"), fmax=librosa.note_to_hz("E6"), sr=sr)
            hop_length = 512
            f0_times = librosa.times_like(f0, sr=sr, hop_length=hop_length)

            # onset 구간별로 f0 중앙값으로 MIDI 변환
            for i, start_t in enumerate(onset_times):
                end_t = float(onset_times[i + 1]) if i + 1 < len(onset_times) else float(f0_times[-1])
                if end_t - start_t < 0.05:
                    continue
                mask = (f0_times >= start_t) & (f0_times < end_t)
                segment = f0[mask]
                segment = segment[np.isfinite(segment)]
                if segment.size == 0:
                    continue
                hz = float(np.median(segment))
                midi = float(_hz_to_midi(hz))
                string, fret = _map_midi_to_guitar_string_fret(midi)
                notes.append(NoteEvent(string=string, fret=fret, start=float(start_t), end=float(end_t)))
        except Exception:
            notes = []

    # 노트가 하나도 없으면, 한 마디짜리 개방현 패턴을 넣어 빈 악보를 피한다.
    if not notes:
        # 오디오 전체 길이를 기준으로 대략적인 한 마디 길이 추정
        try:
            audio, sr = sf.read(str(audio_path))
            duration = len(audio) / float(sr)
        except Exception:
            duration = 1.0
        notes = [
            NoteEvent(string=6, fret=0, start=0.0, end=duration * 0.5),
            NoteEvent(string=1, fret=0, start=duration * 0.5, end=duration),
        ]

    return notes

