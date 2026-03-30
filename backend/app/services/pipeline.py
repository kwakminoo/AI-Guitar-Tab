from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pretty_midi

GUITAR_OPEN_MIDI = [64, 59, 55, 50, 45, 40]  # E4, B3, G3, D3, A2, E2


@dataclass
class PipelineResult:
    job_dir: Path
    mp3_path: Path
    stems: dict[str, Path]
    midi_path: Path
    alphatex: str


def _safe_job_name(url: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "-", url).strip("-").lower()
    cleaned = cleaned[:40] if cleaned else "youtube"
    short_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned}-{short_hash}"


def _run(command: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"명령 실행 실패: {' '.join(command)}\n{stderr}")


def _download_mp3(url: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "source.mp3"
    _run(["yt-dlp", "-x", "--audio-format", "mp3", "-o", str(target), url])
    if not target.exists():
        raise RuntimeError("yt-dlp 다운로드 후 mp3 파일을 찾지 못했습니다.")
    return target


def _separate_demucs(mp3_path: Path, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _run(["python", "-m", "demucs.separate", "-n", "htdemucs", "--mp3", "-o", str(out_dir), str(mp3_path)])
    # demucs output: <out_dir>/htdemucs/<track_name>/*.mp3
    candidates = sorted((out_dir / "htdemucs").glob("*"))
    if not candidates:
        raise RuntimeError("Demucs 결과 폴더를 찾지 못했습니다.")
    track_dir = candidates[0]
    stems = {}
    for name in ("vocals", "drums", "bass", "other", "guitar", "piano"):
        matched = list(track_dir.glob(f"{name}.*"))
        if matched:
            stems[name] = matched[0]
    # guitar/piano가 없는 모델에서도 최소 stems 반환
    return stems


def _basic_pitch_to_midi(guitar_audio: Path, midi_out: Path) -> Path:
    midi_out.parent.mkdir(parents=True, exist_ok=True)
    _run(["basic-pitch", str(midi_out.parent), str(guitar_audio)])
    produced = sorted(midi_out.parent.glob("*.mid"))
    if not produced:
        raise RuntimeError("Basic Pitch 변환 결과 MIDI 파일을 찾지 못했습니다.")
    produced[0].replace(midi_out)
    return midi_out


def _midi_note_to_string_fret(midi_pitch: int) -> tuple[int, int]:
    # 가장 낮은 프렛 우선 매핑
    best = (6, max(0, midi_pitch - GUITAR_OPEN_MIDI[-1]))
    for string_idx, open_pitch in enumerate(GUITAR_OPEN_MIDI, start=1):
        fret = midi_pitch - open_pitch
        if 0 <= fret <= 24:
            if fret < best[1]:
                best = (string_idx, fret)
    return best


def _duration_to_token(duration_sec: float, tempo: float) -> str:
    quarter = 60.0 / max(1.0, tempo)
    units = max(1, round(duration_sec / (quarter / 4.0)))  # 16분음표 단위
    return f":{units}"


def _midi_to_alphatex(midi_path: Path, title: str) -> str:
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    tempo = 120.0
    tempi, _ = midi.get_tempo_changes()
    if len(tempi) > 0:
        tempo = float(tempi[0])

    notes = []
    for inst in midi.instruments:
        for note in inst.notes:
            s, f = _midi_note_to_string_fret(note.pitch)
            notes.append((note.start, note.end, s, f))
    notes.sort(key=lambda n: n[0])

    tokens: list[str] = []
    for start, end, string_no, fret in notes:
        _ = start
        dur = _duration_to_token(max(0.05, end - start), tempo)
        tokens.append(f"{fret}.{string_no}{dur}")
        if len(tokens) % 16 == 0:
            tokens.append("|")

    if not tokens:
        tokens = ["0.6:4", "|"]

    body = " ".join(tokens)
    return (
        f"\\title \"{title}\"\n"
        "\\instrument 25\n"
        f"\\tempo {int(round(tempo))}\n"
        ".\n"
        + body
    )


def run_four_step_pipeline(
    url: str,
    *,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> PipelineResult:
    def report(progress: int, stage: str, detail: str) -> None:
        if progress_cb:
            progress_cb({"type": "progress", "progress": progress, "stage": stage, "detail": detail})

    job_dir = Path("data") / "jobs" / _safe_job_name(url)
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    (job_dir / "audio").mkdir(parents=True, exist_ok=True)

    report(5, "download", "yt-dlp로 mp3 다운로드 시작")
    mp3_path = _download_mp3(url, job_dir / "audio")

    report(30, "separate", "Demucs로 stem 분리 시작")
    stems = _separate_demucs(mp3_path, job_dir / "stems")

    guitar_audio = stems.get("guitar") or stems.get("other")
    if not guitar_audio:
        raise RuntimeError("Demucs 출력에서 guitar/other stem을 찾지 못했습니다.")

    report(60, "basic-pitch", "Basic Pitch로 MIDI 변환 시작")
    midi_path = _basic_pitch_to_midi(guitar_audio, job_dir / "midi" / "guitar.mid")

    report(85, "alphatex", "MIDI를 AlphaTex 문법으로 변환 시작")
    alphatex = _midi_to_alphatex(midi_path, title=job_dir.name)
    (job_dir / "tab").mkdir(parents=True, exist_ok=True)
    (job_dir / "tab" / "guitar.alphatex").write_text(alphatex, encoding="utf-8")
    (job_dir / "tab" / "summary.json").write_text(
        json.dumps(
            {
                "url": url,
                "mp3_path": str(mp3_path),
                "stems": {k: str(v) for k, v in stems.items()},
                "midi_path": str(midi_path),
                "alphatex_path": str(job_dir / "tab" / "guitar.alphatex"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report(100, "done", "4단계 파이프라인 완료")

    return PipelineResult(job_dir=job_dir, mp3_path=mp3_path, stems=stems, midi_path=midi_path, alphatex=alphatex)
