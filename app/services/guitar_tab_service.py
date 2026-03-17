from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH


@dataclass(frozen=True)
class NoteEvent:
    start: float
    end: float
    midi: int
    velocity: float


@dataclass(frozen=True)
class TabNote:
    string: int  # 1 = high E, 6 = low E
    fret: int
    start: float
    end: float


@dataclass(frozen=True)
class TabResult:
    key: str
    capo_fret: int
    notes: List[TabNote]


STANDARD_TUNING_MIDI = np.array([40, 45, 50, 55, 59, 64])  # E2, A2, D3, G3, B3, E4 (6→1번줄)


def extract_notes_with_basic_pitch(audio_path: Path) -> List[NoteEvent]:
    """
    basic-pitch의 predict 함수를 사용해 음표 정보를 추출한다.
    반환되는 note_events는 (start_time, end_time, midi, amplitude) 튜플들의 리스트라고 가정한다.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"기타 오디오 파일을 찾을 수 없습니다: {audio_path}")

    note_events, _, _ = predict(str(audio_path), model_or_model_path=ICASSP_2022_MODEL_PATH)

    result: List[NoteEvent] = []
    for ev in note_events:
        start_t, end_t, midi, vel = ev  # 기본 구조: (start, end, midi, velocity)
        result.append(
            NoteEvent(
                start=float(start_t),
                end=float(end_t),
                midi=int(midi),
                velocity=float(vel),
            )
        )
    return result


def _choose_string_and_fret(midi_note: int, capo_fret: int, max_fret: int = 20) -> Optional[TabNote]:
    """
    주어진 MIDI 음을 표준 튜닝 + Capo 기준으로 어떤 줄/프렛에 배치할지 선택.
    가장 낮은 프렛(연주하기 쉬운 포지션)을 우선으로 선택한다.
    """
    # 6번줄(인덱스 0)~1번줄(인덱스 5)
    best: Optional[tuple[int, int]] = None  # (string_index, fret)
    for idx, open_midi in enumerate(STANDARD_TUNING_MIDI):
        # Capo가 있으면 실제 개방음이 반음 상승
        effective_open = open_midi + capo_fret
        fret = midi_note - effective_open
        if 0 <= fret <= max_fret:
            if best is None or fret < best[1]:
                best = (idx, fret)

    if best is None:
        return None

    string_index, fret = best
    string_number = 6 - string_index  # 6→1, 0→6
    return TabNote(string=string_number, fret=fret, start=0.0, end=0.0)  # 시간은 호출부에서 세팅


def notes_to_tab(
    notes: List[NoteEvent],
    key: str,
    capo_preferred_for_db_major: int = 1,
) -> TabResult:
    """
    - Key가 'Db Major'라면:
      - Capo 1을 적용한다고 가정하고,
      - 실제 소리는 Db Major지만, 연주자는 C Major 포지션을 치게 하기 위해
        모든 음을 1반음 내려서(C Major 스케일) TAB 상에서 표기한다.
    - 그 외의 Key에서는 Capo 0, 원음 기준 표기.
    """
    key_normalized = key.strip().lower()
    if key_normalized.startswith("db") and "major" in key_normalized:
        capo_fret = capo_preferred_for_db_major
        transpose_semitones = -1  # Db → C
    else:
        capo_fret = 0
        transpose_semitones = 0

    tab_notes: List[TabNote] = []

    for n in notes:
        midi = n.midi + transpose_semitones
        base_tab = _choose_string_and_fret(midi_note=midi, capo_fret=capo_fret)
        if base_tab is None:
            continue
        tab_notes.append(
            TabNote(
                string=base_tab.string,
                fret=base_tab.fret,
                start=n.start,
                end=n.end,
            )
        )

    return TabResult(key=key, capo_fret=capo_fret, notes=tab_notes)

