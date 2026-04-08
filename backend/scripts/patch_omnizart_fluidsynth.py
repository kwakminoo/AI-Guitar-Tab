"""Windows fluidsynth.py: 고정 DLL 경로 등록 실패 방지 (pip 재설치 시 재실행)."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: patch_omnizart_fluidsynth.py <path-to-fluidsynth.py>", file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if "if os.path.isdir(_fs_bin)" in text:
        print("Already patched:", path)
        return

    needle = (
        "if hasattr(os, 'add_dll_directory'):  # Python 3.8+ on Windows only\n"
        "    os.add_dll_directory(os.getcwd())\n"
        "    os.add_dll_directory('C:\\\\tools\\\\fluidsynth\\\\bin')\n"
        "    # Workaround bug in find_library, it doesn't recognize add_dll_directory\n"
        "    os.environ['PATH'] += ';C:\\\\tools\\\\fluidsynth\\\\bin'"
    )
    repl = (
        "if hasattr(os, 'add_dll_directory'):  # Python 3.8+ on Windows only\n"
        "    os.add_dll_directory(os.getcwd())\n"
        "    _fs_bin = r\"C:\\\\tools\\\\fluidsynth\\\\bin\"\n"
        "    if os.path.isdir(_fs_bin):\n"
        "        os.add_dll_directory(_fs_bin)\n"
        "        os.environ[\"PATH\"] += \";\" + _fs_bin"
    )
    if needle not in text:
        print("Expected block not found (manual edit or other version):", path, file=sys.stderr)
        sys.exit(1)
    path.write_text(text.replace(needle, repl, 1), encoding="utf-8")
    print("Patched:", path)


if __name__ == "__main__":
    main()
