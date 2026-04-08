"""Omnizart 서브프로세스 전사 스모크 테스트."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    omni_py = _REPO / ".venv_omnizart" / "Scripts" / "python.exe"
    if not omni_py.is_file():
        print("SKIP: .venv_omnizart not found", file=sys.stderr)
        sys.exit(0)
    tmp = Path(tempfile.gettempdir())
    wav = tmp / "omni_smoke.wav"
    mid = tmp / "omni_smoke.mid"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "12",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    sys.path.insert(0, str(_REPO))
    from app.services.omnizart_guitar import transcribe_guitar_stem_to_midi

    transcribe_guitar_stem_to_midi(wav, mid)
    assert mid.is_file() and mid.stat().st_size > 0
    print("OK transcribe_guitar_stem_to_midi ->", mid, mid.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
