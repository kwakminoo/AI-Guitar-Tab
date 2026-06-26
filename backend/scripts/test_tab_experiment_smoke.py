"""
TAB 렌더 모드(transcription/arrangement) 스모크.
실행: backend 디렉터리에서  PYTHONPATH=. python scripts/test_tab_experiment_smoke.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pretty_midi

# backend 루트를 path에 추가
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.pipeline import (  # noqa: E402
    _midi_pitch_to_candidate_positions,
    _render_arrangement_alphatex,
    _render_transcription_alphatex,
)
from app.services.tab_playback import compare_tab_midi_to_reference, string_fret_to_midi_pitch  # noqa: E402


def _clear_tab_env() -> None:
    keys = ["TAB_RENDER_MODE", "TAB_ARRANGEMENT_MIN_RECALL"]
    for k in keys:
        os.environ.pop(k, None)


def _make_tiny_midi(path: Path) -> None:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=25, is_drum=False, name="Guitar")
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=64, start=0.0, end=0.5))
    inst.notes.append(pretty_midi.Note(velocity=78, pitch=67, start=0.5, end=1.0))
    pm.instruments.append(inst)
    pm.write(str(path))


def _assert_capo_mapping_uses_relative_frets() -> None:
    # 카포 2에서 E4를 0.1로 내보내면 alphaTab은 F#4로 재생한다.
    candidates = _midi_pitch_to_candidate_positions(64, capo=2)
    assert (1, 0) not in candidates
    assert (2, 3) in candidates
    assert string_fret_to_midi_pitch(2, 3, capo=2) == 64


def _assert_capo_compare_uses_sounding_pitch() -> None:
    with tempfile.TemporaryDirectory() as td:
        mid = Path(td) / "capo.mid"
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=25, is_drum=False, name="Guitar")
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=64, start=0.0, end=0.5))
        pm.instruments.append(inst)
        pm.write(str(mid))

        report = compare_tab_midi_to_reference(
            mid,
            [{"string": 2, "fret": 3, "start": 0.0, "end": 0.5, "velocity": 80}],
            capo=2,
        )
        assert report["pitch_onset_recall_rate"] == 1.0


def _run_case(name: str, env_updates: dict[str, str], *, mode: str) -> dict:
    _clear_tab_env()
    for k, v in env_updates.items():
        os.environ[k] = v
    with tempfile.TemporaryDirectory() as td:
        mid = Path(td) / "smoke.mid"
        _make_tiny_midi(mid)
        out: dict = {}
        if mode == "arrangement":
            tex = _render_arrangement_alphatex(
                mid,
                title="smoke",
                artist="",
                lyrics=None,
                audio_duration_sec=None,
                capo=0,
                tempo_override=120.0,
                onset_times_sec=None,
                tab_output_dir=None,
                tab_experiment_out=out,
                arrangement_relax_level=0,
            )
        else:
            tex = _render_transcription_alphatex(
                mid,
                title="smoke",
                artist="",
                lyrics=None,
                audio_duration_sec=None,
                capo=0,
                tempo_override=120.0,
                onset_times_sec=None,
                tab_output_dir=None,
                tab_experiment_out=out,
            )
        assert "\\title" in tex
        assert out.get("boundary_count_after", 0) >= 1
        assert out.get("render_mode") == mode
    print(f"[ok] {name} keys={sorted(env_updates.keys()) or 'default'}")
    return out


def main() -> None:
    _assert_capo_mapping_uses_relative_frets()
    _assert_capo_compare_uses_sounding_pitch()
    _run_case("transcription_default", {}, mode="transcription")
    arrangement_out = _run_case(
        "arrangement_mode",
        {
            "TAB_RENDER_MODE": "arrangement",
            "TAB_ARRANGEMENT_MIN_RECALL": "0.80",
        },
        mode="arrangement",
    )
    assert arrangement_out.get("alphatex_rhythm_mode") == "arrangement_eighth"
    _clear_tab_env()
    print("tab render mode smoke: all passed")


if __name__ == "__main__":
    main()
