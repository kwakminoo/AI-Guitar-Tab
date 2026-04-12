"""탭 note_events → MIDI export 및 원본 MIDI와의 온셋 비교."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pretty_midi

GUITAR_OPEN_MIDI = [64, 59, 55, 50, 45, 40]
GUITAR_MIN_PITCH = 40
GUITAR_MAX_PITCH = 88


def string_fret_to_midi_pitch(string_idx: int, fret: int) -> int:
    if string_idx < 1 or string_idx > 6:
        raise ValueError(f"string_idx는 1~6: {string_idx}")
    return int(GUITAR_OPEN_MIDI[string_idx - 1]) + int(fret)


def note_events_to_pretty_midi(
    note_events: list[dict[str, Any]],
    *,
    program: int = 25,
    instrument_name: str = "Guitar Tab Export",
) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=int(program) % 128, name=instrument_name, is_drum=False)
    for n in note_events:
        pitch = string_fret_to_midi_pitch(int(n["string"]), int(n["fret"]))
        vel = max(1, min(127, int(n.get("velocity", 80))))
        st = float(n["start"])
        en = float(n["end"])
        if en <= st:
            continue
        inst.notes.append(pretty_midi.Note(velocity=vel, pitch=pitch, start=st, end=en))
    pm.instruments.append(inst)
    return pm


def export_tab_note_events_to_midi(note_events: list[dict[str, Any]], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    note_events_to_pretty_midi(note_events).write(str(out_path))
    return out_path


def _collect_guitar_notes(midi: pretty_midi.PrettyMIDI) -> list[pretty_midi.Note]:
    out: list[pretty_midi.Note] = []
    for inst in midi.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            if GUITAR_MIN_PITCH <= int(n.pitch) <= GUITAR_MAX_PITCH:
                out.append(n)
    out.sort(key=lambda x: (x.start, x.pitch))
    return out


def compare_tab_midi_to_reference(
    reference_midi_path: Path,
    tab_note_events: list[dict[str, Any]],
    *,
    onset_tolerance_sec: float = 0.06,
) -> dict[str, Any]:
    ref = pretty_midi.PrettyMIDI(str(reference_midi_path))
    ref_notes = _collect_guitar_notes(ref)
    tab_notes: list[tuple[float, int]] = []
    for n in tab_note_events:
        st = float(n["start"])
        en = float(n["end"])
        if en <= st:
            continue
        p = string_fret_to_midi_pitch(int(n["string"]), int(n["fret"]))
        tab_notes.append((st, p))
    tab_notes.sort(key=lambda x: (x[0], x[1]))
    tol = float(onset_tolerance_sec)

    def nearest_ok(query_t: float, pitch: int) -> bool:
        best = tol * 10
        for rn in ref_notes:
            if int(rn.pitch) != pitch:
                continue
            d = abs(float(rn.start) - query_t)
            if d < best:
                best = d
        return best <= tol

    hits = sum(1 for st, p in tab_notes if nearest_ok(st, p))
    onset_match_rate = (hits / len(tab_notes)) if tab_notes else 1.0
    recall_hits = 0
    for rn in ref_notes:
        rs = float(rn.start)
        rp = int(rn.pitch)
        if any(abs(st - rs) <= tol and p == rp for st, p in tab_notes):
            recall_hits += 1
    recall = (recall_hits / len(ref_notes)) if ref_notes else 1.0
    f1 = 0.0 if onset_match_rate + recall <= 1e-9 else 2 * onset_match_rate * recall / (onset_match_rate + recall)
    return {
        "tab_note_count": len(tab_notes),
        "reference_guitar_note_count": len(ref_notes),
        "onset_match_rate": round(float(onset_match_rate), 4),
        "pitch_onset_recall_rate": round(float(recall), 4),
        "f1_onset_symmetric": round(float(f1), 4),
        "onset_tolerance_sec": tol,
    }


def nudge_note_events_toward_reference(
    note_events: list[dict[str, Any]],
    reference_midi_path: Path,
    *,
    onset_tolerance_sec: float = 0.055,
) -> list[dict[str, Any]]:
    """원본과 피치·온셋이 가까우면 탭 노트 시작만 원본 온셋에 맞춘다."""
    ref = pretty_midi.PrettyMIDI(str(reference_midi_path))
    ref_notes = _collect_guitar_notes(ref)
    tol = float(onset_tolerance_sec)
    out: list[dict[str, Any]] = []
    for n in note_events:
        cp = {**n}
        pitch = string_fret_to_midi_pitch(int(cp["string"]), int(cp["fret"]))
        st = float(cp["start"])
        best: pretty_midi.Note | None = None
        best_d = tol * 10
        for rn in ref_notes:
            if int(rn.pitch) != pitch:
                continue
            d = abs(float(rn.start) - st)
            if d < best_d:
                best_d = d
                best = rn
        if best is not None and best_d <= tol:
            cp["start"] = float(best.start)
        out.append(cp)
    return out


def refine_note_events_with_reference_midi(
    note_events: list[dict[str, Any]],
    reference_midi_path: Path,
    *,
    max_passes: int = 2,
    onset_tolerance_sec: float = 0.055,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    passes: list[dict[str, Any]] = []
    cur = [{**x} for x in note_events]
    best = cur
    best_f1 = -1.0
    for i in range(max(1, int(max_passes))):
        rep = compare_tab_midi_to_reference(
            reference_midi_path, cur, onset_tolerance_sec=onset_tolerance_sec
        )
        f1 = float(rep["f1_onset_symmetric"])
        passes.append({"pass": i, **rep})
        if f1 > best_f1 + 1e-6:
            best_f1 = f1
            best = [{**x} for x in cur]
        if i + 1 >= max_passes:
            break
        nxt = nudge_note_events_toward_reference(
            cur, reference_midi_path, onset_tolerance_sec=onset_tolerance_sec
        )
        same = len(nxt) == len(cur) and all(
            abs(float(a["start"]) - float(b["start"])) < 1e-5
            for a, b in zip(nxt, cur, strict=False)
        )
        if same:
            break
        cur = nxt
    return best, passes


def write_tab_compare_artifacts(
    reference_midi_path: Path,
    note_events: list[dict[str, Any]],
    tab_dir: Path,
    *,
    refine: bool = True,
) -> dict[str, Any]:
    tab_dir.mkdir(parents=True, exist_ok=True)
    final_notes = list(note_events)
    report: dict[str, Any] = {"refine_enabled": bool(refine)}
    if refine:
        final_notes, passes = refine_note_events_with_reference_midi(
            note_events, reference_midi_path, max_passes=2
        )
        report["refine_passes"] = passes
    else:
        report["refine_passes"] = []
    export_tab_note_events_to_midi(final_notes, tab_dir / "tab_from_tab.mid")
    report["compare_before_refine"] = compare_tab_midi_to_reference(reference_midi_path, note_events)
    report["compare_after_export"] = compare_tab_midi_to_reference(reference_midi_path, final_notes)
    report["note_event_count"] = len(final_notes)
    (tab_dir / "compare_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
