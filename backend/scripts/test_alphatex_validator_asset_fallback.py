"""
AlphaTex validator should work from committed frontend assets without npm install.
Run from repo root: python3 backend/scripts/test_alphatex_validator_asset_fallback.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _stub_module(name: str, **attrs: object) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


def _install_pipeline_import_stubs() -> None:
    _stub_module("pretty_midi", PrettyMIDI=object)
    _stub_module(
        "app.services.beat_audio",
        analyze_onsets_from_guitar_audio=lambda *args, **kwargs: [],
        snap_midi_notes_to_sixteenth_grid=lambda *args, **kwargs: None,
        snap_midi_notes_to_tempo_grid=lambda *args, **kwargs: None,
    )
    _stub_module(
        "app.services.lyrics_lrclib",
        fetch_lyrics_from_lrclib=lambda *args, **kwargs: (None, "none"),
        parse_artist_and_track_from_youtube_title=lambda title: ("", title),
    )
    _stub_module("app.services.omnizart_guitar", extract_guitar_tab_hints_from_midi=lambda *args, **kwargs: [])
    _stub_module(
        "app.services.tab_playback",
        refine_note_events_with_reference_midi=lambda *args, **kwargs: [],
        write_tab_compare_artifacts=lambda *args, **kwargs: None,
    )


def main() -> None:
    asset_path = _ROOT / "frontend" / "public" / "alphatab-assets" / "alphaTab.mjs"
    assert asset_path.is_file(), f"missing committed alphaTab asset: {asset_path}"

    _install_pipeline_import_stubs()
    from app.services.pipeline import _validate_alphatex_with_alphatab

    tex = "\n".join(
        [
            '\\title "validator smoke"',
            '\\artist ""',
            '\\track "Guitar" { instrument "Acoustic Guitar Steel" }',
            "\\staff {score tabs}",
            "\\ts (4 4)",
            "\\tuning (E4 B3 G3 D3 A2 E2)",
            "\\tempo 120",
            ":4",
            "0.1 1.2 2.3 3.4 |",
        ]
    )
    diag = _validate_alphatex_with_alphatab(tex)
    assert diag.get("tokenGuard", {}).get("ok") is True, diag
    assert diag.get("hasErrors") is False, diag
    print("alphatex validator asset fallback: ok")


if __name__ == "__main__":
    main()
