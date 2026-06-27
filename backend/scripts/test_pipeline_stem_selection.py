"""Pipeline MIDI source stem selection regression tests."""
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pretty_midi_stub = types.ModuleType("pretty_midi")
pretty_midi_stub.PrettyMIDI = object
pretty_midi_stub.Instrument = object
pretty_midi_stub.Note = object
sys.modules.setdefault("pretty_midi", pretty_midi_stub)

from app.services import pipeline  # noqa: E402


def _quality(playable: bool) -> dict:
    return {
        "exists": True,
        "is_playable_source": playable,
        "rms_db": -18.0 if playable else -120.0,
        "onset_count": 8 if playable else 0,
    }


def test_other_stem_is_used_when_guitar_stem_is_missing() -> None:
    original_analyze = pipeline._analyze_stem_quality
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stems_root = root / "stems"
            stems_root.mkdir()
            mix_mp3 = root / "source.mp3"
            other_mp3 = stems_root / "other.mp3"
            mix_mp3.write_bytes(b"mix")
            other_mp3.write_bytes(b"other")
            stems = {"other": other_mp3}

            pipeline._analyze_stem_quality = lambda path: _quality(Path(path).name == "other.mp3")

            selected = pipeline._select_midi_source_stem(stems, stems_root, mix_mp3)

            assert selected.selected_source == "guitar"
            assert selected.selected_stem_mp3 == stems_root / "guitar.mp3"
            assert selected.selected_stem_mp3.read_bytes() == b"other"
            assert stems["guitar"] == selected.selected_stem_mp3
            assert "other stem" in selected.midi_source_reason
    finally:
        pipeline._analyze_stem_quality = original_analyze


def test_piano_stem_is_used_when_guitar_and_other_are_unusable() -> None:
    original_analyze = pipeline._analyze_stem_quality
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stems_root = root / "stems"
            stems_root.mkdir()
            mix_mp3 = root / "source.mp3"
            other_mp3 = stems_root / "other.mp3"
            piano_mp3 = stems_root / "piano.mp3"
            mix_mp3.write_bytes(b"mix")
            other_mp3.write_bytes(b"other")
            piano_mp3.write_bytes(b"piano")
            stems = {"other": other_mp3, "piano": piano_mp3}

            pipeline._analyze_stem_quality = lambda path: _quality(Path(path).name == "piano.mp3")

            selected = pipeline._select_midi_source_stem(stems, stems_root, mix_mp3)

            assert selected.selected_source == "piano"
            assert selected.selected_stem_mp3 == piano_mp3
            assert selected.midi_source_reason == "guitar 무효 + piano stem 품질 통과"
    finally:
        pipeline._analyze_stem_quality = original_analyze


def main() -> None:
    test_other_stem_is_used_when_guitar_stem_is_missing()
    test_piano_stem_is_used_when_guitar_and_other_are_unusable()
    print("pipeline stem selection tests: all passed")


if __name__ == "__main__":
    main()
