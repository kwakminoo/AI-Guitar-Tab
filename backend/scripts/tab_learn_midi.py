"""
MIDI 마디별 피치클래스 집계 (tab 학습용).
입력: guitar.mid 경로, job_meta.json 경로(선택, beat_times_sec 사용).
출력: stdout에 JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pretty_midi


def _collect_notes(pm: pretty_midi.PrettyMIDI) -> list[tuple[float, float, int]]:
    out: list[tuple[float, float, int]] = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            out.append((float(n.start), float(n.end), int(n.pitch)))
    out.sort(key=lambda x: x[0])
    return out


def _beats_per_bar_from_midi(pm: pretty_midi.PrettyMIDI) -> int:
    if pm.time_signature_changes:
        ts = pm.time_signature_changes[0]
        num = int(ts.numerator)
        den = int(ts.denominator)
        if den == 4:
            return num
        if den == 8 and num == 6:
            return 6
        return max(1, num)
    return 4


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: tab_learn_midi.py <guitar.mid> [job_meta.json]", file=sys.stderr)
        sys.exit(2)
    midi_path = Path(sys.argv[1])
    meta_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    notes = _collect_notes(pm)
    bpb = _beats_per_bar_from_midi(pm)
    duration = float(pm.get_end_time())

    beats: list[float] = []
    if meta_path and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        beats = [float(x) for x in meta.get("beat_times_sec", []) if isinstance(x, (int, float))]

    bars: list[dict] = []

    if len(beats) >= bpb + 1:
        n_bars = len(beats) // bpb
        for i in range(n_bars):
            t0 = beats[i * bpb]
            t1 = beats[i * bpb + bpb] if i * bpb + bpb < len(beats) else max(duration, t0 + 0.01)
            pcs: dict[int, int] = {}
            for st, en, p in notes:
                if st < t1 and en > t0:
                    pc = p % 12
                    pcs[pc] = pcs.get(pc, 0) + 1
            top = sorted(pcs.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
            bars.append(
                {
                    "index": i,
                    "t0": t0,
                    "t1": t1,
                    "pitchClassCounts": {str(k): v for k, v in sorted(pcs.items())},
                    "topPitchClasses": [k for k, _ in top],
                }
            )
    else:
        bpm = 120.0
        _, tempos = pm.get_tempo_changes()
        if len(tempos) > 0:
            bpm = float(tempos[0])
        bpm = max(40.0, min(240.0, bpm))
        sec_per_beat = 60.0 / bpm
        bar_sec = sec_per_beat * bpb
        n_bars = max(1, int(duration / bar_sec) + 1)
        for i in range(n_bars):
            t0 = i * bar_sec
            t1 = (i + 1) * bar_sec
            pcs = {}
            for st, en, p in notes:
                if st < t1 and en > t0:
                    pc = p % 12
                    pcs[pc] = pcs.get(pc, 0) + 1
            top = sorted(pcs.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
            bars.append(
                {
                    "index": i,
                    "t0": t0,
                    "t1": t1,
                    "pitchClassCounts": {str(k): v for k, v in sorted(pcs.items())},
                    "topPitchClasses": [k for k, _ in top],
                }
            )

    out = {
        "midiPath": str(midi_path).replace("\\", "/"),
        "durationSec": duration,
        "beatsPerBar": bpb,
        "beatTimesUsed": len(beats),
        "barCount": len(bars),
        "bars": bars,
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
