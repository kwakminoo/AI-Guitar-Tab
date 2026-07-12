"""
MIDI 소스 스템 선택 회귀 테스트.
실행: backend 디렉터리에서  PYTHONPATH=. python scripts/test_pipeline_source_selection.py
"""

from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path

# 클라우드 최소 이미지에서도 순수 선택 로직만 검증할 수 있게 무거운 MIDI 모듈을 대체한다.
sys.modules.setdefault("pretty_midi", types.ModuleType("pretty_midi"))

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.pipeline import _select_midi_source_stem  # noqa: E402


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"mp3")
    return path


def _quality(playable: bool) -> dict[str, bool]:
    return {"is_playable_source": playable}


def test_other_stem_is_used_before_mix_fallback() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = _touch(root / "source.mp3")
        other = _touch(root / "stems" / "other.mp3")
        stems = {"other": other}

        selected_source, selected_path, reason = _select_midi_source_stem(
            stems,
            root / "stems",
            source,
            _quality(False),
            _quality(False),
        )

        assert selected_source == "other"
        assert selected_path == other
        assert "other stem fallback" in reason


def test_playable_guitar_and_piano_priority() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = _touch(root / "source.mp3")
        guitar = _touch(root / "stems" / "guitar.mp3")
        piano = _touch(root / "stems" / "piano.mp3")
        other = _touch(root / "stems" / "other.mp3")
        stems = {"guitar": guitar, "piano": piano, "other": other}

        selected_source, selected_path, _ = _select_midi_source_stem(
            stems,
            root / "stems",
            source,
            _quality(True),
            _quality(True),
        )
        assert selected_source == "guitar"
        assert selected_path == guitar

        selected_source, selected_path, _ = _select_midi_source_stem(
            stems,
            root / "stems",
            source,
            _quality(False),
            _quality(True),
        )
        assert selected_source == "piano"
        assert selected_path == piano


def test_mix_fallback_only_when_no_target_stems_exist() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = _touch(root / "source.mp3")

        selected_source, selected_path, reason = _select_midi_source_stem(
            {},
            root / "stems",
            source,
            _quality(False),
            _quality(False),
        )

        assert selected_source == "fallback"
        assert selected_path == source
        assert "mix(source.mp3)" in reason


def main() -> None:
    test_other_stem_is_used_before_mix_fallback()
    test_playable_guitar_and_piano_priority()
    test_mix_fallback_only_when_no_target_stems_exist()
    print("pipeline source selection: all passed")


if __name__ == "__main__":
    main()
