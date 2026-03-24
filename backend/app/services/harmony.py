from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .transcribe import NoteEvent


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
GUITAR_STRING_MIDI = [64, 59, 55, 50, 45, 40]  # string 1..6


@dataclass
class HarmonyAnalysis:
    key: str
    capo: int
    chords: List[str]


def _note_to_midi(ev: NoteEvent) -> int:
    s_idx = max(1, min(6, int(ev.string))) - 1
    fret = max(0, int(ev.fret))
    return GUITAR_STRING_MIDI[s_idx] + fret


def _best_key_from_histogram(hist: List[float]) -> tuple[int, str]:
    # 간단한 장/단 스케일 적합도 기반 (경량)
    major_template = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    minor_template = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

    best_score = -1.0
    best_root = 0
    best_mode = "major"

    for root in range(12):
        major_score = 0.0
        minor_score = 0.0
        for pc in range(12):
            major_score += hist[pc] * major_template[(pc - root) % 12]
            minor_score += hist[pc] * minor_template[(pc - root) % 12]
        if major_score > best_score:
            best_score = major_score
            best_root = root
            best_mode = "major"
        if minor_score > best_score:
            best_score = minor_score
            best_root = root
            best_mode = "minor"

    return best_root, best_mode


def _estimate_capo(root: int, mode: str) -> int:
    friendly_major = [0, 7, 2, 9, 4]  # C G D A E
    friendly_minor = [9, 4, 2]  # Am Em Dm
    candidates = friendly_major if mode == "major" else friendly_minor

    best = 0
    for capo in range(0, 8):
        shape_root = (root - capo) % 12
        if shape_root in candidates:
            best = capo
            break
    return best


def _estimate_chords(notes: List[NoteEvent], tempo: int, max_bars: int = 8) -> List[str]:
    if not notes:
        return ["C" for _ in range(max_bars)]

    beat_period = (60.0 / max(40, min(220, tempo)))
    bar_duration = beat_period * 4.0
    bar_hists: List[List[float]] = [[0.0] * 12 for _ in range(max_bars)]

    for ev in notes:
        midi = _note_to_midi(ev)
        pc = midi % 12
        bar_idx = int(max(0.0, ev.start) // bar_duration)
        if 0 <= bar_idx < max_bars:
            bar_hists[bar_idx][pc] += max(0.05, ev.end - ev.start)

    triads = []
    for root in range(12):
        triads.append((f"{NOTE_NAMES[root]}", [root, (root + 4) % 12, (root + 7) % 12]))  # major
        triads.append((f"{NOTE_NAMES[root]}m", [root, (root + 3) % 12, (root + 7) % 12]))  # minor

    out: List[str] = []
    prev_name = "C"
    for hist in bar_hists:
        if sum(hist) <= 0:
            out.append(prev_name)
            continue
        best_name = "C"
        best_score = -1.0
        for name, pcs in triads:
            score = hist[pcs[0]] * 1.3 + hist[pcs[1]] + hist[pcs[2]]
            if score > best_score:
                best_score = score
                best_name = name
        if not out or out[-1] != best_name:
            pass
        out.append(best_name)
        prev_name = best_name

    if not out:
        return ["C" for _ in range(max_bars)]
    return out[:max_bars]


def _estimate_chords_with_meter(
    notes: List[NoteEvent],
    tempo: int,
    *,
    time_signature_numerator: int,
    max_bars: int,
) -> List[str]:
    if not notes:
        return ["C" for _ in range(max_bars)]

    beat_period = (60.0 / max(40, min(220, tempo)))
    bar_duration = beat_period * max(1, int(time_signature_numerator))
    bar_hists: List[List[float]] = [[0.0] * 12 for _ in range(max_bars)]

    for ev in notes:
        midi = _note_to_midi(ev)
        pc = midi % 12
        bar_idx = int(max(0.0, ev.start) // bar_duration)
        if 0 <= bar_idx < max_bars:
            bar_hists[bar_idx][pc] += max(0.05, ev.end - ev.start)

    triads = []
    for root in range(12):
        triads.append((f"{NOTE_NAMES[root]}", [root, (root + 4) % 12, (root + 7) % 12]))  # major
        triads.append((f"{NOTE_NAMES[root]}m", [root, (root + 3) % 12, (root + 7) % 12]))  # minor

    out: List[str] = []
    prev_name = "C"
    for hist in bar_hists:
        if sum(hist) <= 0:
            out.append(prev_name)
            continue

        best_name = "C"
        best_score = -1.0
        for name, pcs in triads:
            score = hist[pcs[0]] * 1.3 + hist[pcs[1]] + hist[pcs[2]]
            if score > best_score:
                best_score = score
                best_name = name

        out.append(best_name)
        prev_name = best_name

    return out[:max_bars] if out else ["C" for _ in range(max_bars)]


def analyze_harmony(
    notes: List[NoteEvent],
    tempo: int = 90,
    *,
    time_signature_numerator: int = 4,
    max_bars: int = 8,
) -> HarmonyAnalysis:
    if not notes:
        return HarmonyAnalysis(key="C major", capo=0, chords=["C" for _ in range(max_bars)])

    hist = [0.0] * 12
    for ev in notes:
        midi = _note_to_midi(ev)
        hist[midi % 12] += max(0.05, ev.end - ev.start)

    root, mode = _best_key_from_histogram(hist)
    key = f"{NOTE_NAMES[root]} {mode}"
    capo = _estimate_capo(root, mode)
    chords = _estimate_chords_with_meter(
        notes,
        tempo=tempo,
        time_signature_numerator=time_signature_numerator,
        max_bars=max_bars,
    )
    return HarmonyAnalysis(key=key, capo=capo, chords=chords)

