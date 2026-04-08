"""
Omnizart 기반 기타 스템 → MIDI 변환 및 탭(줄·프렛) 힌트 추출.

공식 omnizart(0.5.x)에는 `omnizart.guitar` 패키지가 없을 수 있으며, 이 경우
`MusicTranscription` + 내장 Pop/Stream 등 체크포인트로 단일 기타 스템을 전사한다.

MIDI에 줄·프렛이 들어오는 경로(택일):
- 동일 디렉터리의 `*.omz_tab.json` 사이드카(권장·안정적)
- Lyric/Marker/Text 메타에 `3/5`, `S3F5`, `str 2 | 7` 형태가 붙은 경우(실험적)
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pretty_midi

_TAB_JSON_SUFFIX = ".omz_tab.json"


def _backend_dir() -> Path:
    """`backend/app/services/omnizart_guitar.py` → backend 디렉터리."""
    return Path(__file__).resolve().parents[2]


def _bundled_omnizart_python_exe() -> Path | None:
    """저장소에 포함된 `backend/.venv_omnizart`(Python 3.8) 인터프리터."""
    exe = _backend_dir() / ".venv_omnizart" / "Scripts" / "python.exe"
    return exe if exe.is_file() else None


def _resolve_omnizart_subprocess_python() -> str | None:
    """서브프로세스로 Omnizart를 돌릴 Python 경로 (환경 변수 > 번들 venv)."""
    explicit = (os.environ.get("OMNIZART_PYTHON") or "").strip()
    if explicit:
        return explicit
    bundled = _bundled_omnizart_python_exe()
    if bundled is not None:
        return str(bundled)
    return None

# Lyric/Marker 등에서 줄·프렛 후보를 잡는다 (1~6번 줄, 0~24프렛 가정)
_TAB_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bS([1-6])F(\d{1,2})\b"),
    re.compile(r"(?i)\b(?:str|st|string)\s*([1-6])\s*[/|]\s*(\d{1,2})\b"),
    re.compile(r"(?<![0-9])\b([1-6])\s*[/|]\s*(\d{1,2})\b(?![0-9])"),
)


def _run_ffmpeg_to_wav_44k_mono(src: Path, dst_wav: Path) -> None:
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "44100",
        "-f",
        "wav",
        str(dst_wav),
    ]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "ffmpeg WAV 변환 실패:\n" + (completed.stderr.strip() or completed.stdout.strip() or "unknown")
        )
    if not dst_wav.is_file():
        raise RuntimeError("ffmpeg 후 WAV 파일이 생성되지 않았습니다.")


def _parse_tab_text(text: str) -> tuple[int, int] | None:
    for pat in _TAB_TEXT_PATTERNS:
        m = pat.search(text)
        if m:
            s, f = int(m.group(1)), int(m.group(2))
            if 1 <= s <= 6 and 0 <= f <= 24:
                return s, f
    return None


def _merge_midi_to_single_guitar(midi: pretty_midi.PrettyMIDI, program: int = 25) -> pretty_midi.PrettyMIDI:
    """여러 악기 트랙을 하나의 기타(기본: Electric Guitar Clean) 트랙으로 합친다. 템포·박자 메타는 유지한다."""
    merged = pretty_midi.Instrument(program=int(program) % 128, name="Guitar", is_drum=False)
    for inst in midi.instruments:
        if inst.is_drum:
            continue
        merged.notes.extend(inst.notes)
    merged.notes.sort(key=lambda n: (n.start, n.pitch))
    out = copy.deepcopy(midi)
    out.instruments = [merged]
    return out


def _call_omnizart_music_transcription(wav: Path, midi_out: Path) -> pretty_midi.PrettyMIDI:
    """omnizart.music.app.MusicTranscription 으로 전사."""
    from omnizart.music.app import MusicTranscription  # type: ignore[import-untyped]

    model = (os.environ.get("OMNIZART_MODEL") or "Pop").strip() or "Pop"
    work = midi_out.parent
    work.mkdir(parents=True, exist_ok=True)
    mt = MusicTranscription()
    midi = mt.transcribe(str(wav), model_path=model, output=str(work))
    if midi is None:
        raise RuntimeError("Omnizart transcribe 가 None 을 반환했습니다.")
    return midi


def _call_omnizart_guitar_if_available(wav: Path, midi_out: Path) -> pretty_midi.PrettyMIDI | None:
    """`omnizart.guitar` 가 있으면 사용 (API는 환경마다 다를 수 있어 동적으로 탐색)."""
    try:
        import omnizart.guitar as ozg  # type: ignore[import-not-found]
    except ImportError:
        return None

    for attr in ("GuitarTranscription", "Guitar", "App"):
        cls = getattr(ozg, attr, None)
        if cls is None:
            continue
        try:
            inst = cls()
            transcribe = getattr(inst, "transcribe", None)
            if callable(transcribe):
                work = midi_out.parent
                midi = transcribe(str(wav), output=str(work))
                if midi is not None:
                    return midi
        except Exception:
            continue

    fn = getattr(ozg, "transcribe", None)
    if callable(fn):
        midi = fn(str(wav), output=str(midi_out.parent))
        if midi is not None:
            return midi
    return None


def transcribe_guitar_stem_to_midi(guitar_audio: Path, midi_out: Path) -> Path:
    """
    분리된 기타 오디오(mp3/wav 등)를 Omnizart로 MIDI로 저장한다.

    Python 3.11 백엔드에서는 `backend/.venv_omnizart`(3.8 + omnizart) 서브프로세스를 우선 사용한다.

    환경 변수:
    - OMNIZART_MODEL: 내장 모드 이름 (기본 Pop). 예: Pop, Stream, Piano
    - OMNIZART_PYTHON: omnizart 가 설치된 Python 실행 파일 (미설정 시 `backend/.venv_omnizart` 자동 탐색)
    """
    midi_out.parent.mkdir(parents=True, exist_ok=True)
    sub_py = _resolve_omnizart_subprocess_python()
    if sub_py and Path(sub_py).resolve() != Path(sys.executable).resolve():
        transcribe_via_subprocess_omnizart_python(guitar_audio, midi_out, omnizart_py=sub_py)
        return midi_out

    wav_work = midi_out.parent / f"{midi_out.stem}_omnizart_src.wav"
    suf = guitar_audio.suffix.lower()
    if suf == ".wav":
        try:
            if guitar_audio.resolve() != wav_work.resolve():
                shutil.copy2(guitar_audio, wav_work)
        except OSError as exc:
            raise RuntimeError(f"WAV 작업 복사 실패: {exc}") from exc
    else:
        _run_ffmpeg_to_wav_44k_mono(guitar_audio, wav_work)

    try:
        midi_obj: pretty_midi.PrettyMIDI | None = _call_omnizart_guitar_if_available(wav_work, midi_out)
        if midi_obj is None:
            midi_obj = _call_omnizart_music_transcription(wav_work, midi_out)
    except ImportError as exc:
        raise RuntimeError(omnizart_import_error_hint()) from exc

    midi_obj = _merge_midi_to_single_guitar(midi_obj)
    midi_obj.write(str(midi_out))
    return midi_out


def load_tab_json_sidecar(midi_path: Path) -> list[dict[str, Any]]:
    """
    `<stem>.omz_tab.json` 사이드카 형식:
    [
      {"pitch": 64, "start": 0.12, "string": 3, "fret": 5, "end": 0.45},
      ...
    ]
    start 는 초 단위(오디오·MIDI와 동일 축).
    """
    p = midi_path.with_name(midi_path.stem + _TAB_JSON_SUFFIX)
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            pitch = int(item["pitch"])
            start = float(item["start"])
            string = int(item["string"])
            fret = int(item["fret"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (1 <= string <= 6 and 0 <= fret <= 24):
            continue
        row: dict[str, Any] = {"pitch": pitch, "start": start, "string": string, "fret": fret}
        if item.get("end") is not None:
            try:
                row["end"] = float(item["end"])
            except (TypeError, ValueError):
                pass
        out.append(row)
    return out


def _hints_from_mido_lyrics(midi_path: Path) -> list[dict[str, Any]]:
    """Lyric/Marker/Text 메타에 포함된 `3/5` 류 문자열을 노트 onset 근처에 매칭."""
    try:
        import mido
    except ImportError:
        return []

    mid = mido.MidiFile(str(midi_path))
    tempo = 500000
    t = 0.0

    lyric_times: list[tuple[float, str]] = []
    note_ons: list[tuple[float, int, int]] = []

    for msg in mido.merge_tracks(mid.tracks):
        delta_sec = mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
        t += delta_sec
        if msg.type == "set_tempo":
            tempo = msg.tempo
        elif msg.type in ("lyrics", "marker", "text"):
            text = getattr(msg, "text", "") or ""
            lyric_times.append((t, str(text)))
        elif msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
            note_ons.append((t, int(msg.note), int(getattr(msg, "channel", 0))))

    lyric_times.sort(key=lambda x: x[0])

    hints: list[dict[str, Any]] = []
    for nt, pitch, _ch in note_ons:
        best: tuple[float, str] | None = None
        for lt, txt in lyric_times:
            if lt > nt + 0.12:
                break
            if nt - 0.15 <= lt <= nt + 0.02:
                d = abs(lt - nt)
                if best is None or d < abs(best[0] - nt):
                    best = (lt, txt)
        if best is None:
            continue
        tab = _parse_tab_text(best[1])
        if tab is None:
            continue
        s, f = tab
        hints.append({"pitch": pitch, "start": nt, "string": s, "fret": f, "end": nt})
    return hints


def extract_guitar_tab_hints_from_midi(midi_path: Path) -> list[dict[str, Any]]:
    """
    Omnizart/외부 도구가 남긴 줄·프렛 힌트를 수집한다.
    JSON 사이드카를 우선하고, 없으면 MIDI 가사/마커를 파싱한다.
    """
    merged: dict[tuple[int, int, int], dict[str, Any]] = {}
    # 키: (pitch, start_ms, string) 로 중복 제거
    for row in load_tab_json_sidecar(midi_path):
        ms = int(round(float(row["start"]) * 1000.0))
        key = (int(row["pitch"]), ms, int(row["string"]))
        merged[key] = row
    for row in _hints_from_mido_lyrics(midi_path):
        ms = int(round(float(row["start"]) * 1000.0))
        key = (int(row["pitch"]), ms, int(row["string"]))
        if key not in merged:
            merged[key] = row
    return sorted(merged.values(), key=lambda r: (float(r["start"]), int(r["pitch"])))


def omnizart_import_error_hint() -> str:
    return (
        "omnizart 를 불러올 수 없습니다. Python 3.8~3.9 환경에 omnizart를 설치하거나, "
        "환경 변수 OMNIZART_PYTHON 에 해당 인터프리터 경로를 지정하세요. "
        "로컬 개발 시 GUITAR_TRANSCRIBE_BACKEND=basic_pitch 로 Basic Pitch 로 되돌릴 수 있습니다."
    )


def transcribe_via_subprocess_omnizart_python(
    guitar_audio: Path,
    midi_out: Path,
    *,
    omnizart_py: str,
) -> None:
    """별도 Python(예: 3.9 + omnizart 설치)에서 전사 스크립트를 실행한다."""
    ga = str(guitar_audio.resolve())
    mo = str(midi_out.resolve())
    script = f"""
import copy, os, shutil, subprocess as sp
from pathlib import Path
import pretty_midi as pm
from omnizart.music.app import MusicTranscription

src = Path({ga!r})
midi_out = Path({mo!r})
model = os.environ.get("OMNIZART_MODEL") or "Pop"
midi_out.parent.mkdir(parents=True, exist_ok=True)
wav_work = midi_out.parent / (midi_out.stem + "_omnizart_src.wav")
if src.suffix.lower() == ".wav":
    shutil.copy2(src, wav_work)
else:
    sp.run(["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "44100", "-f", "wav", str(wav_work)], check=True)
mt = MusicTranscription()
midi = mt.transcribe(str(wav_work), model_path=model, output=str(midi_out.parent))
if midi is None:
    raise SystemExit("omnizart returned None")
merged = pm.Instrument(program=25, name="Guitar", is_drum=False)
for inst in midi.instruments:
    if inst.is_drum:
        continue
    merged.notes.extend(inst.notes)
merged.notes.sort(key=lambda n: (n.start, n.pitch))
out = copy.deepcopy(midi)
out.instruments = [merged]
out.write(str(midi_out))
"""
    midi_out.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [omnizart_py, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Omnizart 서브프로세스 전사 실패:\n" + (completed.stderr.strip() or completed.stdout.strip() or "unknown")
        )
    if not midi_out.is_file():
        raise RuntimeError("Omnizart 서브프로세스 후 MIDI 파일이 없습니다.")
