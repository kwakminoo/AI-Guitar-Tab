"""
Regression test for MIDI upload path isolation.

Run from repo root:
  python backend/scripts/test_midi_upload_isolation.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import app.main as backend_main  # noqa: E402


class DummyUpload:
    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


def main() -> None:
    score_paths: list[Path] = []
    alphatex_calls: list[dict[str, Path]] = []

    def fake_midi_to_score(midi_path: Path, **_: Any) -> dict[str, Any]:
        path = Path(midi_path)
        score_paths.append(path)
        return {"meta": {}, "tracks": []}

    def fake_midi_to_alphatex(midi_path: Path, **kwargs: Any) -> str:
        tab_output_dir = Path(kwargs["tab_output_dir"])
        alphatex_calls.append(
            {"midi_path": Path(midi_path), "tab_output_dir": tab_output_dir}
        )
        tab_output_dir.mkdir(parents=True, exist_ok=True)
        (tab_output_dir / "compare_report.json").write_text(
            '{"ok": true}', encoding="utf-8"
        )
        return '\\title "stub" .'

    original_score = backend_main._midi_to_score
    original_alphatex = backend_main._midi_to_alphatex
    original_cwd = Path.cwd()
    try:
        backend_main._midi_to_score = fake_midi_to_score
        backend_main._midi_to_alphatex = fake_midi_to_alphatex
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            first = asyncio.run(
                backend_main.midi_tab_preview(DummyUpload("same.mid", b"first"))
            )
            second = asyncio.run(
                backend_main.midi_tab_preview(DummyUpload("same.mid", b"second"))
            )

            assert first.title == "same"
            assert second.title == "same"
            assert first.tab_quality == {"ok": True}
            assert second.tab_quality == {"ok": True}
            assert len(score_paths) == 2
            assert score_paths[0] != score_paths[1]
            assert score_paths[0].parent != score_paths[1].parent
            assert score_paths[0].read_bytes() == b"first"
            assert score_paths[1].read_bytes() == b"second"
            assert alphatex_calls[0]["tab_output_dir"] != alphatex_calls[1]["tab_output_dir"]
    finally:
        os.chdir(original_cwd)
        backend_main._midi_to_score = original_score
        backend_main._midi_to_alphatex = original_alphatex

    print("midi upload isolation: all passed")


if __name__ == "__main__":
    main()
