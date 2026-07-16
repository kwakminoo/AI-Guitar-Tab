"""
탭 MIDI 온셋 비교 인덱스 회귀 테스트.
실행: backend 디렉터리에서 PYTHONPATH=. python3 scripts/test_tab_playback_index.py
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


try:
    import pretty_midi  # type: ignore[import-not-found]
except ModuleNotFoundError:
    pretty_midi = types.ModuleType("pretty_midi")
    pretty_midi.Note = object
    pretty_midi.Instrument = object
    pretty_midi.PrettyMIDI = object
    sys.modules["pretty_midi"] = pretty_midi

from app.services import tab_playback


class CountingNote:
    start_reads = 0

    def __init__(self, pitch: int, start: float) -> None:
        self.pitch = pitch
        self._start = start
        self.end = start + 0.05
        self.velocity = 80

    @property
    def start(self) -> float:
        type(self).start_reads += 1
        return self._start


class FakeInstrument:
    is_drum = False

    def __init__(self, notes: list[CountingNote]) -> None:
        self.notes = notes


class FakeMidi:
    def __init__(self, notes: list[CountingNote]) -> None:
        self.instruments = [FakeInstrument(notes)]


class TabPlaybackIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_pretty_midi = tab_playback.pretty_midi.PrettyMIDI

    def tearDown(self) -> None:
        tab_playback.pretty_midi.PrettyMIDI = self._original_pretty_midi

    def test_compare_indexes_onsets_instead_of_rescanning_all_notes(self) -> None:
        count = 200
        references = [
            CountingNote(40 + index % 20, index * 0.1) for index in range(count)
        ]
        tab_events = [
            {
                "string": 6,
                "fret": index % 20,
                "start": index * 0.1,
                "end": index * 0.1 + 0.05,
            }
            for index in range(count)
        ]
        tab_playback.pretty_midi.PrettyMIDI = lambda _path: FakeMidi(references)
        CountingNote.start_reads = 0

        report = tab_playback.compare_tab_midi_to_reference(
            Path("reference.mid"), tab_events
        )

        self.assertEqual(report["f1_onset_symmetric"], 1.0)
        self.assertLessEqual(CountingNote.start_reads, count * 4)

    def test_nudge_preserves_earlier_match_when_distances_are_equal(self) -> None:
        references = [CountingNote(40, 0.75), CountingNote(40, 1.25)]
        tab_playback.pretty_midi.PrettyMIDI = lambda _path: FakeMidi(references)

        nudged = tab_playback.nudge_note_events_toward_reference(
            [
                {
                    "string": 6,
                    "fret": 0,
                    "start": 1.0,
                    "end": 1.5,
                }
            ],
            Path("reference.mid"),
            onset_tolerance_sec=0.3,
        )

        self.assertEqual(nudged[0]["start"], 0.75)


if __name__ == "__main__":
    unittest.main()
