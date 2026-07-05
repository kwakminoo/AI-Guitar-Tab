"""
Stem quality window selection regression test.
Run from repo root: python3 backend/scripts/test_stem_quality_windows.py
"""

from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path

import numpy as np


def _install_pretty_midi_stub() -> None:
    if "pretty_midi" in sys.modules:
        return
    mod = types.ModuleType("pretty_midi")
    mod.PrettyMIDI = object
    mod.Instrument = object
    mod.Note = object
    sys.modules["pretty_midi"] = mod


def _install_librosa_stub(calls: list[float]) -> None:
    mod = types.ModuleType("librosa")

    def load(path: str, *, sr: int, mono: bool, duration: float, offset: float = 0.0):
        calls.append(round(float(offset), 3))
        sample_count = int(sr * 2)
        if offset < 10.0:
            return np.zeros(sample_count, dtype=np.float32), sr
        return np.full(sample_count, 0.1, dtype=np.float32), sr

    feature = types.SimpleNamespace(
        zero_crossing_rate=lambda **_: np.array([[0.01]], dtype=np.float32),
        spectral_flatness=lambda **_: np.array([[0.01]], dtype=np.float32),
    )

    def onset_detect(*, onset_envelope, **_):
        if float(np.max(onset_envelope)) <= 0.0:
            return []
        return list(range(8))

    onset = types.SimpleNamespace(
        onset_strength=lambda *, y, sr, **_: y,
        onset_detect=onset_detect,
    )
    mod.load = load
    mod.feature = feature
    mod.onset = onset
    sys.modules["librosa"] = mod


def main() -> None:
    _install_pretty_midi_stub()
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from app.services import pipeline

    calls: list[float] = []
    _install_librosa_stub(calls)

    with tempfile.TemporaryDirectory() as td:
        audio_path = Path(td) / "guitar.mp3"
        audio_path.write_bytes(b"stub")

        original_probe = pipeline._probe_audio_duration_sec
        try:
            pipeline._probe_audio_duration_sec = lambda _: 120.0
            quality = pipeline._analyze_stem_quality(audio_path)
        finally:
            pipeline._probe_audio_duration_sec = original_probe

    assert calls[:2] == [0.0, 37.5], calls
    assert quality["is_playable_source"] is True, quality
    assert quality["analysis_offset_sec"] == 37.5, quality
    assert quality["onset_count"] == 8, quality
    assert len(quality["analysis_windows"]) == 2, quality
    print("stem quality window regression: passed")


if __name__ == "__main__":
    main()
