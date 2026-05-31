import asyncio
import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app import main


def test_midi_uploads_with_same_filename_use_isolated_paths() -> None:
    seen_midi_paths: list[Path] = []
    seen_tab_dirs: list[Path] = []

    def fake_score(midi_path: Path, title: str, **_kwargs: Any) -> dict[str, Any]:
        seen_midi_paths.append(midi_path)
        return {
            "version": 1,
            "meta": {"title": title},
            "tracks": [{"beats": []}],
        }

    def fake_alphatex(
        midi_path: Path,
        title: str,
        *,
        tab_output_dir: Path | None = None,
        **_kwargs: Any,
    ) -> str:
        assert midi_path.is_file()
        assert tab_output_dir is not None
        seen_tab_dirs.append(tab_output_dir)
        tab_output_dir.mkdir(parents=True, exist_ok=True)
        (tab_output_dir / "compare_report.json").write_text(
            '{"note_event_count": 0}',
            encoding="utf-8",
        )
        return "\\title \"stub\"\n:4 r |"

    original_score = main._midi_to_score
    original_alphatex = main._midi_to_alphatex
    old_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            main._midi_to_score = fake_score
            main._midi_to_alphatex = fake_alphatex

            first = UploadFile(filename="same.mid", file=BytesIO(b"first-midi"))
            second = UploadFile(filename="same.mid", file=BytesIO(b"second-midi"))

            asyncio.run(main.midi_tab_preview(first))
            asyncio.run(main.midi_tab_preview(second))

            assert len(seen_midi_paths) == 2
            assert seen_midi_paths[0] != seen_midi_paths[1]
            assert seen_midi_paths[0].read_bytes() == b"first-midi"
            assert seen_midi_paths[1].read_bytes() == b"second-midi"
            assert len(seen_tab_dirs) == 2
            assert seen_tab_dirs[0] != seen_tab_dirs[1]
        finally:
            main._midi_to_score = original_score
            main._midi_to_alphatex = original_alphatex
            os.chdir(old_cwd)
