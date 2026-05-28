"""
카포가 있는 탭의 프렛 후보와 비교 MIDI pitch 회귀 테스트.
실행: backend 디렉터리에서  PYTHONPATH=. python scripts/test_capo_playback.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pretty_midi

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.pipeline import (  # noqa: E402
    TRANSCRIPTION_PRESET,
    _midi_pitch_to_candidate_positions,
    _quantized_beats_from_midi,
)
from app.services.tab_playback import (  # noqa: E402
    compare_tab_midi_to_reference,
    note_events_to_pretty_midi,
    string_fret_to_midi_pitch,
)


def _make_single_note_midi(path: Path, *, pitch: int = 64, start: float = 0.0) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=25, is_drum=False, name="Guitar")
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=start + 0.5))
    pm.instruments.append(inst)
    pm.write(str(path))
    return pm


def test_capo_candidates_sound_at_reference_pitch() -> None:
    candidates = _midi_pitch_to_candidate_positions(64, capo=2)

    assert candidates
    assert (2, 3) in candidates
    assert (2, 5) not in candidates
    assert all(
        string_fret_to_midi_pitch(string_no, fret, capo=2) == 64
        for string_no, fret in candidates
    )


def test_quantized_mapping_uses_capo_adjusted_fret() -> None:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=25, is_drum=False, name="Guitar")
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=64, start=0.0, end=0.5))
    pm.instruments.append(inst)

    beats, _step = _quantized_beats_from_midi(
        pm,
        120.0,
        preset=TRANSCRIPTION_PRESET,
        capo=2,
    )
    notes = [n for beat in beats for n in beat["notes"]]

    assert notes
    assert notes[0]["string"] == 2
    assert notes[0]["fret"] == 3
    assert string_fret_to_midi_pitch(notes[0]["string"], notes[0]["fret"], capo=2) == 64


def test_compare_and_export_apply_capo_to_pitch() -> None:
    tab_events = [{"string": 2, "fret": 3, "start": 0.0, "end": 0.5, "velocity": 80}]
    tab_midi = note_events_to_pretty_midi(tab_events, capo=2)

    assert [n.pitch for inst in tab_midi.instruments for n in inst.notes] == [64]

    with tempfile.TemporaryDirectory() as td:
        ref_path = Path(td) / "ref.mid"
        _make_single_note_midi(ref_path, pitch=64)
        no_capo = compare_tab_midi_to_reference(ref_path, tab_events, capo=0)
        with_capo = compare_tab_midi_to_reference(ref_path, tab_events, capo=2)

    assert no_capo["pitch_onset_recall_rate"] == 0.0
    assert with_capo["pitch_onset_recall_rate"] == 1.0


def main() -> None:
    test_capo_candidates_sound_at_reference_pitch()
    test_quantized_mapping_uses_capo_adjusted_fret()
    test_compare_and_export_apply_capo_to_pitch()
    print("capo playback tests: all passed")


if __name__ == "__main__":
    main()
