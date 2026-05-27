"""
AlphaTex note duration regression test.
실행: backend 디렉터리에서  PYTHONPATH=. python scripts/test_alphatex_note_durations.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pretty_midi

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import pipeline  # noqa: E402


def _make_short_note_midi(path: Path) -> None:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=25, is_drum=False, name="Guitar")
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=64, start=0.0, end=0.25))
    pm.instruments.append(inst)
    pm.write(str(path))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        mid = Path(td) / "short.mid"
        _make_short_note_midi(mid)
        with patch.object(
            pipeline,
            "_validate_alphatex_with_alphatab",
            return_value={"tokenGuard": {"ok": True}, "hasErrors": False, "errors": [], "astIssues": []},
        ):
            tex = pipeline._midi_to_alphatex(mid, title="short", tempo_override=120.0)

    body = tex.split("\\tempo 120\n", 1)[1].split("\\sync", 1)[0]
    assert ":16 0.1" in body, body
    assert ":1 0.1" not in body, body
    print("alphatex note duration regression: passed")


if __name__ == "__main__":
    main()
