"""
MIDI 소스 스템 선택 회귀 테스트.
실행: backend 디렉터리에서  PYTHONPATH=. python3 scripts/test_pipeline_source_selection.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.pipeline import _select_midi_source_stem  # noqa: E402


class PipelineSourceSelectionTest(unittest.TestCase):
    def test_uses_other_stem_as_guitar_fallback_for_four_stem_demucs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stems_root = root / "stems"
            stems_root.mkdir()
            mix = root / "source.mp3"
            other = stems_root / "other.mp3"
            mix.write_bytes(b"mix")
            other.write_bytes(b"other-stem")

            source, selected, reason = _select_midi_source_stem(
                {"other": other},
                stems_root,
                mix,
                {"is_playable_source": False},
                {"is_playable_source": False},
            )

            self.assertEqual(source, "guitar")
            self.assertEqual(selected, stems_root / "guitar.mp3")
            self.assertEqual(selected.read_bytes(), b"other-stem")
            self.assertIn("other stem", reason)

    def test_playable_guitar_stem_still_wins(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stems_root = root / "stems"
            stems_root.mkdir()
            mix = root / "source.mp3"
            guitar = stems_root / "nested-guitar.mp3"
            other = stems_root / "other.mp3"
            mix.write_bytes(b"mix")
            guitar.write_bytes(b"guitar-stem")
            other.write_bytes(b"other-stem")

            source, selected, reason = _select_midi_source_stem(
                {"guitar": guitar, "other": other},
                stems_root,
                mix,
                {"is_playable_source": True},
                {"is_playable_source": False},
            )

            self.assertEqual(source, "guitar")
            self.assertEqual(selected, stems_root / "guitar.mp3")
            self.assertEqual(selected.read_bytes(), b"guitar-stem")
            self.assertIn("품질 통과", reason)

    def test_falls_back_to_mix_when_no_stem_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stems_root = root / "stems"
            stems_root.mkdir()
            mix = root / "source.mp3"
            mix.write_bytes(b"mix")

            source, selected, reason = _select_midi_source_stem(
                {},
                stems_root,
                mix,
                {"is_playable_source": False},
                {"is_playable_source": False},
            )

            self.assertEqual(source, "fallback")
            self.assertEqual(selected, mix)
            self.assertIn("mix", reason)


if __name__ == "__main__":
    unittest.main()
