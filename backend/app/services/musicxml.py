from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import xml.etree.ElementTree as ET

from .transcribe import NoteEvent


_STRING_OPEN_MIDI = {
    1: 64,  # E4
    2: 59,  # B3
    3: 55,  # G3
    4: 50,  # D3
    5: 45,  # A2
    6: 40,  # E2
}

_STEP_TO_SEMITONE = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}


@dataclass
class ParsedMusicXml:
    notes_by_beat: Dict[int, List[NoteEvent]]
    tempo: int


def _midi_to_pitch_parts(midi: int) -> tuple[str, int, int]:
    semitone = midi % 12
    octave = (midi // 12) - 1
    names = [
        ("C", 0),
        ("C", 1),
        ("D", 0),
        ("D", 1),
        ("E", 0),
        ("F", 0),
        ("F", 1),
        ("G", 0),
        ("G", 1),
        ("A", 0),
        ("A", 1),
        ("B", 0),
    ]
    step, alter = names[semitone]
    return step, alter, octave


def _pitch_parts_to_midi(step: str, alter: int, octave: int) -> int:
    return (octave + 1) * 12 + _STEP_TO_SEMITONE.get(step, 0) + alter


def build_musicxml_from_beats(
    beat_times: List[float],
    notes_by_beat: Dict[int, List[NoteEvent]],
    *,
    title: str,
    artist: str,
    tempo: int,
    time_signature_numerator: int,
) -> str:
    root = ET.Element("score-partwise", version="3.1")
    movement_title = ET.SubElement(root, "movement-title")
    movement_title.text = title

    identification = ET.SubElement(root, "identification")
    creator = ET.SubElement(identification, "creator", type="composer")
    creator.text = artist

    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    part_name = ET.SubElement(score_part, "part-name")
    part_name.text = "Guitar"

    part = ET.SubElement(root, "part", id="P1")

    beats_per_bar = max(1, int(time_signature_numerator))
    beat_count = len(beat_times)
    bar_count = max(1, (beat_count + beats_per_bar - 1) // beats_per_bar)

    for bar_idx in range(bar_count):
        measure = ET.SubElement(part, "measure", number=str(bar_idx + 1))
        if bar_idx == 0:
            attributes = ET.SubElement(measure, "attributes")
            divisions = ET.SubElement(attributes, "divisions")
            divisions.text = "1"
            key = ET.SubElement(attributes, "key")
            fifths = ET.SubElement(key, "fifths")
            fifths.text = "0"
            time = ET.SubElement(attributes, "time")
            beats = ET.SubElement(time, "beats")
            beats.text = str(beats_per_bar)
            beat_type = ET.SubElement(time, "beat-type")
            beat_type.text = "4"
            clef = ET.SubElement(attributes, "clef")
            sign = ET.SubElement(clef, "sign")
            sign.text = "TAB"
            line = ET.SubElement(clef, "line")
            line.text = "5"

            direction = ET.SubElement(measure, "direction", placement="above")
            direction_type = ET.SubElement(direction, "direction-type")
            metronome = ET.SubElement(direction_type, "metronome")
            beat_unit = ET.SubElement(metronome, "beat-unit")
            beat_unit.text = "quarter"
            per_minute = ET.SubElement(metronome, "per-minute")
            per_minute.text = str(max(30, min(220, int(tempo))))
            sound = ET.SubElement(direction, "sound", tempo=str(max(30, min(220, int(tempo)))))
            _ = sound

        for local_beat in range(beats_per_bar):
            beat_idx = bar_idx * beats_per_bar + local_beat
            if beat_idx >= beat_count:
                break
            events = notes_by_beat.get(beat_idx, [])
            if not events:
                rest_note = ET.SubElement(measure, "note")
                ET.SubElement(rest_note, "rest")
                duration = ET.SubElement(rest_note, "duration")
                duration.text = "1"
                note_type = ET.SubElement(rest_note, "type")
                note_type.text = "quarter"
                continue

            for note_idx, ev in enumerate(events):
                note = ET.SubElement(measure, "note")
                if note_idx > 0:
                    ET.SubElement(note, "chord")
                midi = _STRING_OPEN_MIDI.get(int(ev.string), 40) + int(ev.fret)
                step, alter, octave = _midi_to_pitch_parts(midi)
                pitch = ET.SubElement(note, "pitch")
                ET.SubElement(pitch, "step").text = step
                if alter != 0:
                    ET.SubElement(pitch, "alter").text = str(alter)
                ET.SubElement(pitch, "octave").text = str(octave)
                ET.SubElement(note, "duration").text = "1"
                ET.SubElement(note, "type").text = "quarter"
                notations = ET.SubElement(note, "notations")
                technical = ET.SubElement(notations, "technical")
                ET.SubElement(technical, "string").text = str(int(ev.string))
                ET.SubElement(technical, "fret").text = str(int(ev.fret))

    xml_body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_body}'


def parse_musicxml_to_notes_by_beat(xml_text: str) -> ParsedMusicXml:
    root = ET.fromstring(xml_text)
    part = root.find("part")
    if part is None:
        return ParsedMusicXml(notes_by_beat={}, tempo=90)

    tempo = 90
    tempo_node = root.find(".//direction/sound")
    if tempo_node is not None and tempo_node.attrib.get("tempo"):
        try:
            tempo = int(float(tempo_node.attrib["tempo"]))
        except ValueError:
            tempo = 90

    beat_seconds = 60.0 / max(1, tempo)
    notes_by_beat: Dict[int, List[NoteEvent]] = {}

    beat_cursor = 0
    for measure in part.findall("measure"):
        for note in measure.findall("note"):
            is_chord = note.find("chord") is not None
            duration_node = note.find("duration")
            duration_beats = 1
            if duration_node is not None and duration_node.text:
                try:
                    duration_beats = max(1, int(duration_node.text))
                except ValueError:
                    duration_beats = 1

            if note.find("rest") is not None:
                if not is_chord:
                    beat_cursor += duration_beats
                continue

            string_node = note.find(".//technical/string")
            fret_node = note.find(".//technical/fret")
            parsed_string = None
            parsed_fret = None

            if string_node is not None and string_node.text:
                try:
                    parsed_string = int(string_node.text)
                except ValueError:
                    parsed_string = None
            if fret_node is not None and fret_node.text:
                try:
                    parsed_fret = int(fret_node.text)
                except ValueError:
                    parsed_fret = None

            if parsed_string is None or parsed_fret is None:
                step = note.findtext("pitch/step", default="E")
                alter_text = note.findtext("pitch/alter", default="0")
                octave_text = note.findtext("pitch/octave", default="4")
                try:
                    alter = int(alter_text)
                except ValueError:
                    alter = 0
                try:
                    octave = int(octave_text)
                except ValueError:
                    octave = 4
                midi = _pitch_parts_to_midi(step, alter, octave)
                candidates = []
                for string_no, open_midi in _STRING_OPEN_MIDI.items():
                    fret = midi - open_midi
                    if 0 <= fret <= 24:
                        candidates.append((abs(fret), string_no, fret))
                if candidates:
                    _, parsed_string, parsed_fret = sorted(candidates, key=lambda x: x[0])[0]
                else:
                    parsed_string, parsed_fret = 6, max(0, midi - _STRING_OPEN_MIDI[6])

            start = beat_cursor * beat_seconds
            end = (beat_cursor + duration_beats) * beat_seconds
            notes_by_beat.setdefault(beat_cursor, []).append(
                NoteEvent(
                    string=int(parsed_string),
                    fret=int(parsed_fret),
                    start=float(start),
                    end=float(end),
                )
            )
            if not is_chord:
                beat_cursor += duration_beats

    return ParsedMusicXml(notes_by_beat=notes_by_beat, tempo=tempo)
