"""
Score JSON render preset regression test.
Run from backend/: PYTHONPATH=. python scripts/test_score_render_preset.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pretty_midi

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.pipeline import ARRANGEMENT_PRESET, TRANSCRIPTION_PRESET, _midi_to_score  # noqa: E402


def _make_off_grid_midi(path: Path) -> None:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=25, is_drum=False, name="Guitar")
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=64, start=0.125, end=0.375))
    pm.instruments.append(inst)
    pm.write(str(path))


def _first_note_time(score: dict) -> float:
    beats = score["tracks"][0]["beats"]
    return float(beats[0]["notes"][0]["start"])


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        midi_path = Path(td) / "off-grid.mid"
        _make_off_grid_midi(midi_path)

        transcription = _midi_to_score(
            midi_path,
            title="preset-regression",
            tempo_override=120.0,
            preset=TRANSCRIPTION_PRESET,
        )
        arrangement = _midi_to_score(
            midi_path,
            title="preset-regression",
            tempo_override=120.0,
            preset=ARRANGEMENT_PRESET,
        )

    assert _first_note_time(transcription) == 0.125
    assert _first_note_time(arrangement) == 0.0
    print("score render preset regression: all passed")


if __name__ == "__main__":
    main()
