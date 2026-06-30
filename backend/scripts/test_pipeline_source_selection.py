"""
MIDI 입력 음원 선택 회귀 테스트.
실행: backend 디렉터리에서 PYTHONPATH=. python scripts/test_pipeline_source_selection.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.pipeline import _select_midi_source_stem  # noqa: E402


_INVALID_QUALITY = {"exists": False, "is_playable_source": False}
_PLAYABLE_QUALITY = {"exists": True, "is_playable_source": True}


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _run_other_fallback_case() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stems_root = root / "stems"
        mix = _write(root / "source.mp3", b"mix")
        other = _write(root / "demucs" / "other.mp3", b"other")
        stems = {"other": other}

        source, selected, reason = _select_midi_source_stem(
            stems,
            stems_root,
            mix,
            _INVALID_QUALITY,
            _INVALID_QUALITY,
        )

        assert source == "guitar"
        assert selected == stems_root / "guitar.mp3"
        assert selected.read_bytes() == b"other"
        assert stems["guitar"] == selected
        assert "other stem fallback" in reason


def _run_piano_preferred_over_other_case() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stems_root = root / "stems"
        mix = _write(root / "source.mp3", b"mix")
        piano = _write(root / "demucs" / "piano.mp3", b"piano")
        other = _write(root / "demucs" / "other.mp3", b"other")
        stems = {"piano": piano, "other": other}

        source, selected, reason = _select_midi_source_stem(
            stems,
            stems_root,
            mix,
            _INVALID_QUALITY,
            _PLAYABLE_QUALITY,
        )

        assert source == "piano"
        assert selected == stems_root / "piano.mp3"
        assert selected.read_bytes() == b"piano"
        assert "piano stem 품질 통과" in reason


def _run_mix_fallback_case() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mix = _write(root / "source.mp3", b"mix")

        source, selected, reason = _select_midi_source_stem(
            {},
            root / "stems",
            mix,
            _INVALID_QUALITY,
            _INVALID_QUALITY,
        )

        assert source == "fallback"
        assert selected == mix
        assert "mix(source.mp3) fallback" in reason


def main() -> None:
    _run_other_fallback_case()
    _run_piano_preferred_over_other_case()
    _run_mix_fallback_case()
    print("pipeline source selection: all passed")


if __name__ == "__main__":
    main()
