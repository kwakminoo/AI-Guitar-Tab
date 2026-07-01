"""
Demucs stem source selection regression tests.

실행: 저장소 루트에서 python3 backend/scripts/test_pipeline_source_selection.py
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path


if "pretty_midi" not in sys.modules:
    pretty_midi_stub = types.ModuleType("pretty_midi")
    pretty_midi_stub.PrettyMIDI = object
    pretty_midi_stub.Instrument = object
    pretty_midi_stub.Note = object
    sys.modules["pretty_midi"] = pretty_midi_stub

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import pipeline  # noqa: E402


class PipelineSourceSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_analyze = pipeline._analyze_stem_quality

    def tearDown(self) -> None:
        pipeline._analyze_stem_quality = self._orig_analyze

    def test_other_stem_is_used_as_guitar_for_four_stem_demucs_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stems_root = root / "stems"
            stems_root.mkdir()
            mix_mp3 = root / "source.mp3"
            other_mp3 = stems_root / "other.mp3"
            mix_mp3.write_bytes(b"full mix")
            other_mp3.write_bytes(b"separated other")

            def fake_analyze(audio_path: Path) -> dict:
                return {
                    "exists": audio_path.is_file(),
                    "is_playable_source": audio_path.name == "guitar.mp3",
                    "rms_db": -20.0,
                    "onset_count": 12,
                }

            pipeline._analyze_stem_quality = fake_analyze

            selected_source, selected_stem, reason, guitar_quality, _piano_quality, guitar_mp3 = (
                pipeline._select_midi_source_stem({"other": other_mp3}, stems_root, mix_mp3)
            )

            self.assertEqual(selected_source, "guitar")
            self.assertEqual(selected_stem, stems_root / "guitar.mp3")
            self.assertEqual(guitar_mp3, stems_root / "guitar.mp3")
            self.assertEqual((stems_root / "guitar.mp3").read_bytes(), b"separated other")
            self.assertTrue(guitar_quality["is_playable_source"])
            self.assertIn("other fallback", reason)

    def test_full_mix_is_used_when_no_target_stems_exist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stems_root = root / "stems"
            stems_root.mkdir()
            mix_mp3 = root / "source.mp3"
            mix_mp3.write_bytes(b"full mix")

            selected_source, selected_stem, _reason, _guitar_quality, _piano_quality, guitar_mp3 = (
                pipeline._select_midi_source_stem({}, stems_root, mix_mp3)
            )

            self.assertEqual(selected_source, "fallback")
            self.assertEqual(selected_stem, mix_mp3)
            self.assertEqual(guitar_mp3, mix_mp3)


if __name__ == "__main__":
    unittest.main()
