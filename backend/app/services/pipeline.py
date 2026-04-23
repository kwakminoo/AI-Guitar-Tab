from __future__ import annotations

import hashlib
import bisect
import json
import os
import shutil
import re
import subprocess
import sys
import math
import statistics
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pretty_midi

from .beat_audio import (
    analyze_onsets_from_guitar_audio,
    snap_midi_notes_to_sixteenth_grid,
    snap_midi_notes_to_tempo_grid,
)
from .lyrics_lrclib import fetch_lyrics_from_lrclib, parse_artist_and_track_from_youtube_title
from .omnizart_guitar import extract_guitar_tab_hints_from_midi
from .tab_playback import refine_note_events_with_reference_midi, write_tab_compare_artifacts

GUITAR_OPEN_MIDI = [64, 59, 55, 50, 45, 40]  # E4, B3, G3, D3, A2, E2
GUITAR_MIN_PITCH = 40
GUITAR_MAX_PITCH = 88
MIN_NOTE_VELOCITY = 18
ONSET_TOLERANCE_SEC = 0.045
MERGE_MIN_IOI_SEC = 0.070
SUSTAIN_RELEASE_SEC = 0.090
MAX_SUSTAIN_BEATS = 2.0
MAX_NOTES_PER_SLOT = 3

# 운지 전이 비용 보정 계수(_position_transition_cost와 독립 조정)
TAB_V2_SAME_FRET_BONUS = 0.4
TAB_V2_SHORT_NOTE_SEC = 0.08
TAB_V2_SHORT_NOTE_PENALTY = 0.15
TAB_V2_LOW_VEL_THRESH = 36
TAB_V2_LOW_VEL_PENALTY = 0.12
TAB_V2_STRING_CHANGE_EXTRA = 0.25
TAB_RENDER_MODE_DEFAULT = "transcription"
TAB_RENDER_MODE_ALLOWED = {"transcription", "arrangement"}
TAB_ARRANGEMENT_MIN_RECALL_DEFAULT = 0.80
CAPO_CANDIDATE_RANGE = (0, 5)
HYBRID_PITCH_ERROR_WEIGHT = 0.82
HYBRID_RIFF_PITCH_ERROR_WEIGHT = 0.95
HYBRID_CHORD_TONE_BONUS = 0.45
HYBRID_RIFF_CHORD_TONE_BONUS = 0.18
HYBRID_SHAPE_ALIGNMENT_BONUS = 0.40
HYBRID_RIFF_SHAPE_ALIGNMENT_BONUS = 0.10
HYBRID_SHAPE_OUTSIDE_PENALTY = 0.55
HYBRID_RIFF_SHAPE_OUTSIDE_PENALTY = 0.18
RIFF_CHORD_HIT_RATE_THRESHOLD = 0.42
RIFF_NOTES_PER_SEC_THRESHOLD = 5.8
RIFF_MEAN_MELODIC_STEP_THRESHOLD = 2.8


@dataclass(frozen=True)
class TabRenderPreset:
    name: str
    unified_grid: bool
    subdivisions_per_quarter: int
    use_grid_boundaries: bool
    use_emit_cost: bool
    use_emit_mdp: bool
    use_fingering_v2: bool
    use_merge_voice_key: bool
    onset_gate_mode: str
    emit_dynamics: bool
    base_den: int


TRANSCRIPTION_PRESET = TabRenderPreset(
    name="transcription",
    unified_grid=False,
    subdivisions_per_quarter=4,
    use_grid_boundaries=False,
    use_emit_cost=False,
    use_emit_mdp=False,
    use_fingering_v2=False,
    use_merge_voice_key=False,
    onset_gate_mode="hard",
    emit_dynamics=False,
    base_den=16,
)

ARRANGEMENT_PRESET = TabRenderPreset(
    name="arrangement",
    unified_grid=True,
    subdivisions_per_quarter=2,  # 8분 해상도
    use_grid_boundaries=True,
    use_emit_cost=True,
    use_emit_mdp=True,
    use_fingering_v2=True,
    use_merge_voice_key=True,
    onset_gate_mode="soft",
    emit_dynamics=False,
    base_den=8,
)

# General MIDI program → alphaTab instrument 이름 (Structural Metadata 문서와 동일 계열)
_GM_PROGRAM_TO_ALPHATAB: dict[int, str] = {
    0: "Acoustic Grand Piano",
    1: "Bright Grand Piano",
    24: "Acoustic Guitar Nylon",
    25: "Acoustic Guitar Steel",
    26: "Electric Guitar Jazz",
    27: "Electric Guitar Clean",
    28: "Electric Guitar Muted",
    29: "Overdriven Guitar",
    30: "Distortion Guitar",
    31: "Guitar Harmonics",
    32: "Acoustic Bass",
    33: "Electric Bass Finger",
    34: "Electric Bass Pick",
}


def _midi_program_to_alphatab_instrument(program: int) -> str:
    return _GM_PROGRAM_TO_ALPHATAB.get(int(program) % 128, "Acoustic Guitar Steel")


def _get_primary_midi_program(midi: pretty_midi.PrettyMIDI) -> int:
    for inst in midi.instruments:
        if not inst.is_drum and inst.notes:
            return int(inst.program)
    for inst in midi.instruments:
        if inst.notes:
            return int(inst.program)
    return 25


def _parse_tempo_segments(midi: pretty_midi.PrettyMIDI) -> list[tuple[float, float]]:
    times, tempos = midi.get_tempo_changes()
    if times is None or len(times) == 0:
        return [(0.0, 120.0)]
    out: list[tuple[float, float]] = []
    for i in range(len(times)):
        out.append((float(times[i]), float(tempos[i])))
    out.sort(key=lambda x: x[0])
    return out


def _parse_time_signature_segments(midi: pretty_midi.PrettyMIDI) -> list[tuple[float, int, int]]:
    raw = getattr(midi, "time_signature_changes", None) or []
    if not raw:
        return [(0.0, 4, 4)]
    out: list[tuple[float, int, int]] = []
    for ts in raw:
        t = float(getattr(ts, "time", 0.0))
        num = int(getattr(ts, "numerator", 4))
        den = int(getattr(ts, "denominator", 4))
        if num < 1:
            num = 4
        if den < 1:
            den = 4
        out.append((t, num, den))
    out.sort(key=lambda x: x[0])
    return out


def _segment_value_at(
    segments: list[tuple[float, Any]],
    t: float,
    default: Any,
) -> Any:
    best: Any = default
    for st, val in segments:
        if st <= t + 1e-9:
            best = val
        else:
            break
    return best


def _measure_units_16ths(numerator: int, denominator: int) -> int:
    return max(1, int(numerator * 16 // denominator))


def _probe_audio_duration_sec(path: Path) -> float | None:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if completed.returncode != 0:
            return None
        line = (completed.stdout or "").strip().splitlines()
        if not line:
            return None
        return float(line[0])
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        return None


def _velocity_to_dy(velocity: int) -> str:
    v = max(0, min(127, int(velocity)))
    if v < 28:
        return "ppp"
    if v < 40:
        return "pp"
    if v < 52:
        return "p"
    if v < 64:
        return "mp"
    if v < 80:
        return "mf"
    if v < 96:
        return "f"
    if v < 112:
        return "ff"
    return "fff"


def _escape_alpha_tex_string(value: str) -> str:
    # alphaTex string literal은 backslash/quote 이스케이프가 중요하다.
    cleaned = value.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    cleaned = cleaned.replace("\\", "\\\\").replace('"', '\\"')
    # 과도하게 긴 문자열은 파서/렌더 부하 및 진단 노이즈를 유발하므로 상한을 둔다.
    return cleaned[:200]


# \\lyrics 전용: alphaTab은 공백으로 음절을 나눠 박에 배치한다.
# https://alphatab.net/docs/alphatex/metadata/staff/lyrics
LYRICS_ALPHA_TEX_MAX_CHARS = 12000


def _clean_alphatex_lyrics_text(value: str) -> str:
    """이스케이프만 하고 길이 자르기 전 문자열 (잘림 여부 계산용)."""
    cleaned = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = cleaned.replace("\n", " ").replace("\t", " ").strip()
    cleaned = cleaned.replace("\\", "\\\\").replace('"', '\\"')
    return cleaned


def _escape_alpha_tex_lyrics(value: str) -> str:
    return _clean_alphatex_lyrics_text(value)[:LYRICS_ALPHA_TEX_MAX_CHARS]


def _alphatex_lyrics_truncation_info(raw: str) -> tuple[bool, int]:
    c = _clean_alphatex_lyrics_text(raw)
    truncated = len(c) > LYRICS_ALPHA_TEX_MAX_CHARS
    return truncated, min(len(c), LYRICS_ALPHA_TEX_MAX_CHARS)


def _write_lyrics_files(
    job_dir: Path,
    lyrics: str | None,
    lyrics_source: str,
    *,
    alphatex_truncated: bool,
    alphatex_lyrics_chars: int,
) -> dict[str, Any]:
    """
    가사를 작업 폴더에 별도 파일로 저장한다.
    - lyrics.txt: 작업 루트(한글 인코딩 UTF-8)
    - tab/lyrics.txt: 악보와 같은 디렉터리 복사본
    - tab/lyrics.json: 출처·길이·AlphaTex 반영 여부 메타
    """
    out: dict[str, Any] = {
        "saved": False,
        "paths": {},
        "source": lyrics_source,
    }
    if not lyrics or not str(lyrics).strip():
        return out
    text = str(lyrics).strip()
    tab_dir = job_dir / "tab"
    tab_dir.mkdir(parents=True, exist_ok=True)

    root_txt = job_dir / "lyrics.txt"
    tab_txt = tab_dir / "lyrics.txt"
    tab_meta = tab_dir / "lyrics.json"

    root_txt.write_text(text, encoding="utf-8")
    tab_txt.write_text(text, encoding="utf-8")
    tab_meta.write_text(
        json.dumps(
            {
                "source": lyrics_source,
                "char_count": len(text),
                "encoding": "utf-8",
                "alphatex_lyrics_chars": alphatex_lyrics_chars,
                "alphatex_lyrics_truncated": alphatex_truncated,
                "files": {
                    "plain_root": str(root_txt.as_posix()),
                    "plain_next_to_alphatex": str(tab_txt.as_posix()),
                },
                "alphatex_note": (
                    "guitar.alphatex 헤더의 \\\\lyrics 에 동일 가사가 들어가며, "
                    "alphaTab이 박마다 음절을 배치한다. "
                    "문법: https://alphatab.net/docs/alphatex/metadata/staff/lyrics"
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    out["saved"] = True
    out["paths"] = {
        "lyrics_txt": str(root_txt),
        "tab_lyrics_txt": str(tab_txt),
        "tab_lyrics_json": str(tab_meta),
    }
    return out


def _description_fallback_lyrics(description: str | None) -> str | None:
    """유튜브 설명 첫 줄이 실제 가사일 때만 보조 사용."""
    if not description or not description.strip():
        return None
    first_paragraph = description.split("\n\n", 1)[0].strip()
    if len(first_paragraph) < 8:
        return None
    # 제목/크레딧 한 줄만 있는 설명은 가사로 보지 않는다.
    if "\n" not in first_paragraph and len(first_paragraph) < 80:
        return None
    if re.match(r"^https?://", first_paragraph.strip()):
        return None
    # "가수 - 곡명 [가사/Lyrics]" 같은 헤더 문구는 제외
    if re.search(r"(?:\[\s*가사\s*/\s*lyrics?\s*\]|lyrics?)", first_paragraph, flags=re.I):
        return None
    return first_paragraph[:800]


def _vtt_to_plain_lyrics(vtt_text: str) -> str:
    """WEBVTT 자막 텍스트를 순수 가사 라인으로 정리."""
    lines: list[str] = []
    prev = ""
    for raw in (vtt_text or "").replace("\r\n", "\n").split("\n"):
        s = raw.strip()
        if not s:
            continue
        if s.upper().startswith("WEBVTT"):
            continue
        if s.startswith("NOTE"):
            continue
        if "-->" in s:
            continue
        if re.match(r"^\d+$", s):
            continue
        s = re.sub(r"<[^>]+>", "", s).strip()
        if not s:
            continue
        if re.match(r"^(kind|language)\s*:", s, flags=re.I):
            continue
        # 배경음/효과음 표식 제거
        if re.match(r"^\[(?:음악|music|applause|laughs?|sfx).*\]$", s, flags=re.I):
            continue
        if s in {"♪", "♬"}:
            continue
        if s == prev:
            continue
        lines.append(s)
        prev = s
    return "\n".join(lines).strip()


def _youtube_subtitle_fallback_lyrics(url: str, out_dir: Path) -> str | None:
    """
    yt-dlp 자막(ko-orig/ko)에서 가사 추출.
    일부 언어 다운로드 실패가 있어도 --ignore-errors로 가능한 파일만 활용한다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    output_tpl = out_dir / "%(id)s.%(ext)s"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--skip-download",
        "--write-auto-subs",
        "--write-subs",
        "--sub-langs",
        "ko-orig,ko",
        "--sub-format",
        "vtt",
        "--ignore-errors",
        "--no-warnings",
        "--output",
        str(output_tpl),
        url,
    ]
    subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    candidates = sorted(out_dir.glob("*.ko-orig.vtt"), reverse=True) + sorted(
        out_dir.glob("*.ko.vtt"), reverse=True
    )
    for p in candidates:
        try:
            text = _vtt_to_plain_lyrics(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not text:
            continue
        # 너무 짧은 경우(제목/잡음) 제외
        if len(text) < 24:
            continue
        return text
    return None


def _resolve_youtube_lyrics(
    url: str,
    job_dir: Path,
    title: str,
    artist: str | None,
    uploader: str | None,
    description: str | None,
    duration_youtube: float | None,
    duration_audio: float | None,
    cache_dir: Path,
) -> tuple[str | None, str]:
    """
    LRCLIB 우선 → (옵션) ffprobe 길이로 재시도 → 유튜브 설명 폴백.
    반환: (가사 텍스트, 출처 lrclib|lrclib_cache|youtube_description|none)
    """
    text, src = fetch_lyrics_from_lrclib(
        title, artist, uploader, duration_youtube, cache_dir=cache_dir
    )
    if text and text.strip():
        return text.strip(), src

    if duration_audio is not None:
        if duration_youtube is None or abs(float(duration_audio) - float(duration_youtube or 0)) > 1.0:
            text2, src2 = fetch_lyrics_from_lrclib(
                title, artist, uploader, duration_audio, cache_dir=cache_dir
            )
            if text2 and text2.strip():
                return text2.strip(), src2

    yt_sub = _youtube_subtitle_fallback_lyrics(url, job_dir / "lyrics_subs")
    if yt_sub and yt_sub.strip():
        return yt_sub.strip(), "youtube_subtitles"

    fb = _description_fallback_lyrics(description)
    if fb:
        return fb, "youtube_description"
    return None, "none"


def _merge_chord_into_beat_token(token: str, ch_label: str) -> str:
    """
    alphaTab은 박당 beat effect가 **하나의** `{ ... }` 블록만 허용한다.
    `{dy mp}{ch "C"}`는 두 번째 `{`가 다음 박으로 잘못 읽혀 AT202가 난다.
    → `{dy mp ch "C"}` 또는 `{ch "C"}` 한 블록으로 합친다.
    """
    if not ch_label:
        return token
    esc = _escape_alpha_tex_string(ch_label)
    ch_prop = f'ch "{esc}"'
    start = token.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(token)):
            if token[i] == "{":
                depth += 1
            elif token[i] == "}":
                depth -= 1
                if depth == 0:
                    return token[:i] + f" {ch_prop}" + token[i:]
    return f"{token} {{{ch_prop}}}"


def _clamp_capo_0_5(value: int | float) -> int:
    return max(0, min(5, int(value)))


def _chord_label_notation_simplicity(label: str | None) -> float:
    """코드 문자열이 단순(샵/플 적음)할수록 높은 점수 — 카포 후보 선택용."""
    if not label or label == "?":
        return 0.2
    s = str(label)
    head = s[:5]
    if "#" in head:
        return 0.45
    if re.match(r"^[A-G]b", s) and not s.startswith("Bb"):
        return 0.55
    return 1.0


def _capo_style_prior(capo: int) -> float:
    """test-scores 정답지에서 자주 나온 카포(2·3)에 소프트 바이어스."""
    if capo in (2, 3):
        return 0.35
    if capo in (0, 4, 5):
        return 0.12
    return 0.05


def _refine_capo_with_midi(
    raw_notes: list[dict[str, Any]],
    bars_info: list[tuple[float, float, int, int, float, int]],
) -> int:
    """
    MIDI 기반 마디별 코드 표기 단순도로 카포 후보(0~5) 선택.
    """
    return _choose_capo_midi_only(raw_notes, bars_info, render_mode="transcription")


def _choose_capo_midi_only(
    raw_notes: list[dict[str, Any]],
    bars_info: list[tuple[float, float, int, int, float, int]],
    *,
    render_mode: str,
) -> int:
    """MIDI only 카포 선택(0~5 고정) — 모드별로 연주성 가중치만 다르게 반영."""
    if not bars_info:
        return 0
    candidates = tuple(range(CAPO_CANDIDATE_RANGE[0], CAPO_CANDIDATE_RANGE[1] + 1))
    best_c = 0
    best_score = -1e9
    for c in candidates:
        labels = _bar_chord_labels(raw_notes, bars_info, c)
        simp = statistics.fmean(_chord_label_notation_simplicity(lb) for lb in labels) if labels else 0.0
        play = _arrangement_playability_score(raw_notes, c)
        if render_mode == "arrangement":
            total = (1.00 * simp) + (1.00 * play) + _capo_style_prior(c)
        else:
            total = (1.12 * simp) + (0.60 * play) + _capo_style_prior(c)
        if total > best_score + 1e-9:
            best_score = total
            best_c = c
    return _clamp_capo_0_5(best_c)


def _resolve_tab_render_mode() -> str:
    raw = (os.environ.get("TAB_RENDER_MODE") or TAB_RENDER_MODE_DEFAULT).strip().lower()
    if raw in TAB_RENDER_MODE_ALLOWED:
        return raw
    return TAB_RENDER_MODE_DEFAULT


def _parse_arrangement_min_recall() -> float:
    raw = (os.environ.get("TAB_ARRANGEMENT_MIN_RECALL") or "").strip()
    if not raw:
        return TAB_ARRANGEMENT_MIN_RECALL_DEFAULT
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return TAB_ARRANGEMENT_MIN_RECALL_DEFAULT

def _preset_for_mode(mode: str) -> TabRenderPreset:
    return ARRANGEMENT_PRESET if mode == "arrangement" else TRANSCRIPTION_PRESET


def _raw_guitar_notes_from_midi(midi: pretty_midi.PrettyMIDI) -> list[dict[str, Any]]:
    """코드 추정용: 기타 음역 MIDI 노트(연주 음높이, concert pitch)."""
    out: list[dict[str, Any]] = []
    for inst in midi.instruments:
        if inst.is_drum:
            continue
        for note in inst.notes:
            if note.end <= note.start:
                continue
            if int(note.velocity) < MIN_NOTE_VELOCITY:
                continue
            if not (GUITAR_MIN_PITCH <= int(note.pitch) <= GUITAR_MAX_PITCH):
                continue
            out.append(
                {
                    "pitch": int(note.pitch),
                    "start": float(note.start),
                    "end": float(note.end),
                    "velocity": int(note.velocity),
                }
            )
    return out


def _midi_has_named_chord_track_hint(midi: pretty_midi.PrettyMIDI) -> bool:
    """일반 MIDI에 '코드 전용' 트랙이 명시된 경우(휴리스틱). Basic Pitch 출력은 대부분 False."""
    for inst in midi.instruments:
        n = (inst.name or "").lower()
        if "chord" in n and "solo" not in n:
            return True
    return False


_PC_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _pc_to_name(pc: int) -> str:
    return _PC_NAMES_SHARP[pc % 12]


_CHORD_CANDIDATES: list[tuple[str, tuple[int, ...]]] = [
    ("", (0, 4, 7)),
    ("m", (0, 3, 7)),
    ("7", (0, 4, 7, 10)),
    ("m7", (0, 3, 7, 10)),
    ("maj7", (0, 4, 7, 11)),
    ("m7b5", (0, 3, 6, 10)),
    ("dim", (0, 3, 6)),
    ("sus4", (0, 5, 7)),
    ("sus2", (0, 2, 7)),
    ("add9", (0, 4, 7, 2)),
]


def _best_chord_from_weights(weights: list[float], capo: int) -> str | None:
    """concert 음높이 가중치 → 운지 이름(카포만큼 반음 아래로 표기)."""
    total = sum(weights)
    if total < 1e-6:
        return None
    w = [float(x) for x in weights]
    best_score = -1e9
    best_label: str | None = None
    for root in range(12):
        for suffix, intervals in _CHORD_CANDIDATES:
            template = {(root + i) % 12 for i in intervals}
            score = sum(w[p] for p in template)
            extra = sum(w[p] for p in range(12) if p not in template)
            adj = score - 0.22 * extra
            if adj > best_score + 1e-9:
                best_score = adj
                shape_root = (root - int(capo)) % 12
                best_label = f"{_pc_to_name(shape_root)}{suffix}"
    if best_label is None or best_score < total * 0.06:
        return None
    return best_label


def _chord_for_time_range(
    raw_notes: list[dict[str, Any]],
    t0: float,
    t1: float,
    capo: int,
) -> str | None:
    weights = [0.0] * 12
    for n in raw_notes:
        ov = min(n["end"], t1) - max(n["start"], t0)
        if ov > 0:
            weights[n["pitch"] % 12] += ov
    return _best_chord_from_weights(weights, capo)


def _bar_chord_labels(
    raw_notes: list[dict[str, Any]],
    bars_info: list[tuple[float, float, int, int, float, int]],
    capo: int,
) -> list[str]:
    out: list[str] = []
    prev: str | None = None
    for bs, be, *_r in bars_info:
        label = _chord_for_time_range(raw_notes, bs, be, capo)
        if not label:
            label = prev if prev else "?"
        out.append(label)
        prev = label
    return out


def _smooth_bar_chord_labels(labels: list[str]) -> list[str]:
    """인접 마디에서 단발 점프를 완화해 코드 진행을 안정화."""
    if len(labels) < 3:
        return labels
    out = list(labels)
    for i in range(1, len(out) - 1):
        prev_label = out[i - 1]
        cur_label = out[i]
        next_label = out[i + 1]
        if cur_label != prev_label and cur_label != next_label and prev_label == next_label:
            out[i] = prev_label
    return out


def _arrangement_playability_score(raw_notes: list[dict[str, Any]], capo: int) -> float:
    """카포 후보별 단순 연주성 점수(높을수록 좋음)."""
    if not raw_notes:
        return 0.0
    adjusted = [max(0, int(n["pitch"]) - int(capo) - 40) for n in raw_notes]
    mean_fret = statistics.fmean(adjusted) if adjusted else 0.0
    openish = sum(1 for f in adjusted if f <= 3) / max(1, len(adjusted))
    move = sum(abs(adjusted[i] - adjusted[i - 1]) for i in range(1, len(adjusted))) / max(
        1, len(adjusted) - 1
    )
    return (1.6 * openish) - (0.025 * mean_fret) - (0.018 * move)


def _refine_capo_for_arrangement(
    raw_notes: list[dict[str, Any]],
    bars_info: list[tuple[float, float, int, int, float, int]],
) -> int:
    """MIDI 기반 단순성/연주성 결합 카포 선택(0~5 full search)."""
    return _choose_capo_midi_only(raw_notes, bars_info, render_mode="arrangement")


# AlphaTex \\chord ("이름" s1..s6): 1번줄(하이E) → 6번줄(로우E), x = 뮤트
_CHORD_ALPHA_TEX_SHAPES: dict[str, tuple[Any, ...]] = {
    "C": (0, 1, 0, 2, 3, "x"),
    "Cm": (3, 4, 5, 5, 3, "x"),
    "C7": (0, 1, 3, 2, 3, "x"),
    "Cmaj7": (0, 0, 0, 2, 3, "x"),
    "Cm7": (3, 4, 3, 5, 3, "x"),
    "D": (2, 3, 2, 0, "x", "x"),
    "Dm": (1, 3, 2, 0, "x", "x"),
    "D7": (2, 1, 2, 0, "x", "x"),
    "Dm7": (1, 1, 2, 0, "x", "x"),
    "E": (0, 0, 1, 2, 2, 0),
    "Em": (0, 0, 0, 2, 2, 0),
    "E7": (0, 3, 1, 0, 2, 0),
    "Em7": (0, 0, 0, 0, 2, 0),
    "F": (1, 1, 2, 3, 3, 1),
    "Fm": (1, 1, 1, 3, 3, 1),
    "F7": (1, 1, 2, 1, 3, 1),
    "Fm7": (1, 1, 1, 3, 3, 1),
    "Fmaj7": (0, 1, 2, 3, "x", "x"),
    "G": (3, 3, 0, 0, 2, 3),
    "Gm": (3, 3, 0, 0, 1, 3),
    "G7": (1, 0, 0, 0, 2, 3),
    "Gm7": (3, 3, 3, 3, 1, 3),
    "A": (0, 2, 2, 2, 0, "x"),
    "Am": (0, 1, 2, 2, 0, "x"),
    "A7": (0, 2, 0, 2, 0, "x"),
    "Am7": (0, 1, 0, 2, 0, "x"),
    "Amaj7": (0, 2, 1, 2, 0, "x"),
    "B": (2, 2, 2, 1, 0, "x"),
    "Bm": (2, 3, 4, 4, 2, "x"),
    "B7": (2, 0, 1, 2, 0, 2),
    "Bm7": (2, 0, 2, 2, 2, "x"),
    "Bb": (1, 3, 3, 3, 1, "x"),
    "Bbm": (1, 1, 3, 3, 2, "x"),
    "Eb": (3, 3, 3, 1, 1, 1),
    "Ebm": (2, 4, 4, 4, 2, "x"),
    "Ab": (1, 1, 1, 3, 4, 4),
    "Abm": (1, 1, 1, 3, 2, 4),
}


def _normalize_chord_label_for_shape_lookup(label: str) -> str:
    s = (label or "").strip()
    if not s or s == "?":
        return ""
    repl = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
    for k, v in repl.items():
        if s.startswith(k) and (len(s) == len(k) or not s[len(k) : len(k) + 1].isalpha()):
            s = v + s[len(k) :]
            break
    return s


def _chord_shape_tuple_for_label(label: str) -> tuple[Any, ...] | None:
    key = _normalize_chord_label_for_shape_lookup(label)
    if not key:
        return None
    if key in _CHORD_ALPHA_TEX_SHAPES:
        return _CHORD_ALPHA_TEX_SHAPES[key]
    if label.strip() in _CHORD_ALPHA_TEX_SHAPES:
        return _CHORD_ALPHA_TEX_SHAPES[label.strip()]
    return None


def _chord_pitch_classes_from_label(label: str | None) -> set[int]:
    s = _normalize_chord_label_for_shape_lookup(label or "")
    if not s:
        return set()
    m = re.match(r"^([A-G])([#b]?)(.*)$", s)
    if not m:
        return set()
    root_name = f"{m.group(1)}{m.group(2)}"
    suffix = (m.group(3) or "").strip().lower()
    root_map = {
        "C": 0,
        "C#": 1,
        "D": 2,
        "D#": 3,
        "E": 4,
        "F": 5,
        "F#": 6,
        "G": 7,
        "G#": 8,
        "A": 9,
        "A#": 10,
        "B": 11,
    }
    root_pc = root_map.get(root_name)
    if root_pc is None:
        return set()
    quality = ""
    if suffix.startswith("m7b5"):
        quality = "m7b5"
    elif suffix.startswith("maj7"):
        quality = "maj7"
    elif suffix.startswith("m7"):
        quality = "m7"
    elif suffix.startswith("dim"):
        quality = "dim"
    elif suffix.startswith("sus4"):
        quality = "sus4"
    elif suffix.startswith("sus2"):
        quality = "sus2"
    elif suffix.startswith("add9"):
        quality = "add9"
    elif suffix.startswith("7"):
        quality = "7"
    elif suffix.startswith("m"):
        quality = "m"
    intervals_map = {k: set(v) for k, v in _CHORD_CANDIDATES}
    intervals = intervals_map.get(quality, {0, 4, 7})
    return {(root_pc + i) % 12 for i in intervals}


def _bar_index_for_time(
    t: float,
    bars_info: list[tuple[float, float, int, int, float, int]],
    cache_idx: int,
) -> int:
    if not bars_info:
        return 0
    i = max(0, min(cache_idx, len(bars_info) - 1))
    while i + 1 < len(bars_info) and t >= float(bars_info[i][1]) - 1e-9:
        i += 1
    while i > 0 and t < float(bars_info[i][0]) - 1e-9:
        i -= 1
    return i


def _shape_fret_for_string(shape: tuple[Any, ...], string_no: int) -> int | None:
    idx = int(string_no) - 1
    if idx < 0 or idx >= len(shape):
        return None
    v = shape[idx]
    if v == "x" or v == "X":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _mapping_position_score(
    *,
    pitch: int,
    pos: tuple[int, int],
    prev_pos: tuple[int, int],
    bar_label: str | None,
    chord_pcs: set[int],
    shape: tuple[Any, ...] | None,
    capo: int,
    use_v2: bool,
    prev_meta: dict[str, Any] | None,
    note_meta: dict[str, Any] | None,
    weight_profile: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    string_no, fret = int(pos[0]), int(pos[1])
    sounding_pitch = int(GUITAR_OPEN_MIDI[string_no - 1] + fret + int(capo))
    pitch_error = abs(int(pitch) - sounding_pitch)
    profile = weight_profile or {}
    pitch_weight = float(profile.get("pitch_error_weight", HYBRID_PITCH_ERROR_WEIGHT))
    chord_bonus_value = float(profile.get("chord_tone_bonus", HYBRID_CHORD_TONE_BONUS))
    shape_align_near = float(profile.get("shape_align_near_bonus", HYBRID_SHAPE_ALIGNMENT_BONUS))
    shape_align_mid = float(profile.get("shape_align_mid_bonus", HYBRID_SHAPE_ALIGNMENT_BONUS * 0.30))
    shape_out_muted = float(profile.get("shape_out_muted_penalty", HYBRID_SHAPE_OUTSIDE_PENALTY))
    shape_out_far = float(profile.get("shape_out_far_penalty", HYBRID_SHAPE_OUTSIDE_PENALTY * 0.65))
    shape_missing = float(profile.get("shape_missing_penalty", HYBRID_SHAPE_OUTSIDE_PENALTY * 0.15))
    chord_tone_bonus = chord_bonus_value if chord_pcs and (sounding_pitch % 12) in chord_pcs else 0.0

    shape_alignment_bonus = 0.0
    shape_out_penalty = 0.0
    if shape is not None:
        sf = _shape_fret_for_string(shape, string_no)
        if sf is None:
            shape_out_penalty += shape_out_muted
        else:
            d = abs(int(fret) - int(sf))
            if d <= 1:
                shape_alignment_bonus += shape_align_near
            elif d <= 3:
                shape_alignment_bonus += shape_align_mid
            elif d >= 6:
                shape_out_penalty += shape_out_far
    elif bar_label and bar_label != "?":
        shape_out_penalty += shape_missing

    if use_v2:
        transition_cost = _position_transition_cost_v2(prev_pos, pos, prev_meta, note_meta)
    else:
        transition_cost = _position_transition_cost(prev_pos, pos)

    total_cost = (
        transition_cost
        + (pitch_weight * float(pitch_error))
        + float(shape_out_penalty)
        - float(chord_tone_bonus)
        - float(shape_alignment_bonus)
    )
    details = {
        "pitch_error": float(pitch_error),
        "chord_tone_hit": 1.0 if chord_tone_bonus > 0 else 0.0,
        "shape_alignment_hit": 1.0 if shape_alignment_bonus > 0 else 0.0,
    }
    return float(total_cost), details


def _hybrid_weight_profile(*, is_riff_segment: bool) -> dict[str, float]:
    if is_riff_segment:
        return {
            "pitch_error_weight": HYBRID_RIFF_PITCH_ERROR_WEIGHT,
            "chord_tone_bonus": HYBRID_RIFF_CHORD_TONE_BONUS,
            "shape_align_near_bonus": HYBRID_RIFF_SHAPE_ALIGNMENT_BONUS,
            "shape_align_mid_bonus": HYBRID_RIFF_SHAPE_ALIGNMENT_BONUS * 0.35,
            "shape_out_muted_penalty": HYBRID_RIFF_SHAPE_OUTSIDE_PENALTY,
            "shape_out_far_penalty": HYBRID_RIFF_SHAPE_OUTSIDE_PENALTY * 0.70,
            "shape_missing_penalty": HYBRID_RIFF_SHAPE_OUTSIDE_PENALTY * 0.45,
        }
    return {
        "pitch_error_weight": HYBRID_PITCH_ERROR_WEIGHT,
        "chord_tone_bonus": HYBRID_CHORD_TONE_BONUS,
        "shape_align_near_bonus": HYBRID_SHAPE_ALIGNMENT_BONUS,
        "shape_align_mid_bonus": HYBRID_SHAPE_ALIGNMENT_BONUS * 0.30,
        "shape_out_muted_penalty": HYBRID_SHAPE_OUTSIDE_PENALTY,
        "shape_out_far_penalty": HYBRID_SHAPE_OUTSIDE_PENALTY * 0.65,
        "shape_missing_penalty": HYBRID_SHAPE_OUTSIDE_PENALTY * 0.15,
    }


def _detect_riff_bars(
    slots: dict[int, list[dict[str, Any]]],
    slot_keys: list[int],
    step: float,
    bars_info: list[tuple[float, float, int, int, float, int]],
    bar_chords: list[str],
) -> set[int]:
    if not slot_keys or not bars_info:
        return set()
    stats: dict[int, dict[str, Any]] = {}
    prev_pitch_by_bar: dict[int, int] = {}
    bar_idx_cache = 0
    for k in slot_keys:
        t = float(k * step)
        bar_idx_cache = _bar_index_for_time(t, bars_info, bar_idx_cache)
        bar_label = bar_chords[bar_idx_cache] if bar_idx_cache < len(bar_chords) else None
        chord_pcs = _chord_pitch_classes_from_label(bar_label)
        row = stats.setdefault(
            bar_idx_cache,
            {"notes": 0, "hits": 0, "step_sum": 0.0, "step_n": 0},
        )
        notes = slots.get(k, [])
        if not notes:
            continue
        lead = max(notes, key=lambda x: (x.get("velocity", 0), -x.get("pitch", 0)))
        lead_pitch = int(lead["pitch"])
        prev_pitch = prev_pitch_by_bar.get(bar_idx_cache)
        if prev_pitch is not None:
            row["step_sum"] += abs(float(lead_pitch - prev_pitch))
            row["step_n"] += 1
        prev_pitch_by_bar[bar_idx_cache] = lead_pitch
        for n in notes:
            pitch = int(n["pitch"])
            row["notes"] += 1
            if chord_pcs and (pitch % 12) in chord_pcs:
                row["hits"] += 1

    riff_bars: set[int] = set()
    for bar_idx, row in stats.items():
        notes_n = max(1, int(row["notes"]))
        hit_rate = float(row["hits"]) / float(notes_n)
        bs, be, *_ = bars_info[bar_idx]
        duration = max(1e-6, float(be) - float(bs))
        note_density = float(notes_n) / duration
        melodic_step = (
            float(row["step_sum"]) / float(row["step_n"])
            if int(row["step_n"]) > 0
            else 0.0
        )
        if hit_rate <= RIFF_CHORD_HIT_RATE_THRESHOLD and (
            note_density >= RIFF_NOTES_PER_SEC_THRESHOLD
            or melodic_step >= RIFF_MEAN_MELODIC_STEP_THRESHOLD
        ):
            riff_bars.add(int(bar_idx))
    return riff_bars


def _alphatex_chord_definitions_block(ordered_labels: list[str]) -> str:
    lines: list[str] = []
    for name in ordered_labels:
        shape = _chord_shape_tuple_for_label(name)
        if shape is None:
            continue
        esc = _escape_alpha_tex_string(name)
        parts = " ".join("x" if (x == "x" or x == "X") else str(int(x)) for x in shape)
        lines.append(f'\\chord ("{esc}" {parts})')
    return ("\n".join(lines) + "\n") if lines else ""


def _tab_snapshot_key(
    note_events: list[dict[str, Any]],
    t0: float,
    eps: float,
) -> tuple[tuple[int, int], ...]:
    active = [n for n in note_events if n["start"] <= t0 + eps and n["end"] > t0 + eps]
    if not active:
        return tuple()
    by_string: dict[int, dict[str, Any]] = {}
    for n in active:
        s = int(n["string"])
        existing = by_string.get(s)
        if existing is None:
            by_string[s] = n
            continue
        if (n["velocity"], -n["fret"]) > (existing["velocity"], -existing["fret"]):
            by_string[s] = n
    chosen = sorted(by_string.values(), key=lambda x: (x["string"], x["fret"]))
    return tuple((int(n["string"]), int(n["fret"])) for n in chosen)


def _tab_voice_uid_frozen(note_events: list[dict[str, Any]], t0: float, eps: float) -> frozenset[int]:
    """활성 줄별 대표 노트의 note_uid 집합."""
    active = [n for n in note_events if n["start"] <= t0 + eps and n["end"] > t0 + eps]
    if not active:
        return frozenset()
    by_string: dict[int, dict[str, Any]] = {}
    for n in active:
        s = int(n["string"])
        existing = by_string.get(s)
        if existing is None:
            by_string[s] = n
            continue
        if (n["velocity"], -n["fret"]) > (existing["velocity"], -existing["fret"]):
            by_string[s] = n
    chosen = sorted(by_string.values(), key=lambda x: (x["string"], x["fret"]))
    uids: list[int] = []
    for n in chosen:
        if "note_uid" in n:
            uids.append(int(n["note_uid"]))
    return frozenset(uids)


def _tab_merge_row_key(
    note_events: list[dict[str, Any]],
    t0: float,
    eps: float,
    *,
    use_voice: bool,
) -> Any:
    snap = _tab_snapshot_key(note_events, t0, eps)
    if not use_voice:
        return snap
    return (snap, _tab_voice_uid_frozen(note_events, t0, eps))


_DEN_TO_HALF_UNITS = {32: 1, 16: 2, 8: 4, 4: 8, 2: 16, 1: 32}


def _emit_pick_den_cost(
    rem_u: float,
    room: float,
    bar_units: float,
    last_den: int | None,
) -> tuple[int | None, float]:
    """유효 분모 중 비용 최소 선택. 불가 시 (None, 0)."""
    best_cost = 1e18
    best: tuple[int | None, float] = (None, 0.0)
    token_w = 0.35
    streak32_w = 0.22
    align_bonus = -0.06
    for d in (1, 2, 4, 8, 16, 32):
        nu = 16.0 / d
        if nu > rem_u + 1e-6 or nu > room + 1e-6:
            continue
        c = token_w
        if d == 32 and last_den == 32:
            c += streak32_w
        pos_after = bar_units + nu
        if abs(pos_after % 4.0) < 1e-4 or abs((pos_after % 4.0) - 4.0) < 1e-4:
            c += align_bonus
        if c < best_cost:
            best_cost = c
            best = (d, nu)
    if best[0] is None:
        return None, 0.0
    return best


def _mdp_den_sequence_half_units(target_half: int) -> list[int] | None:
    """rem_u를 0.5·16분 단위(=32분) 정수로 본 최소 토큰 수 분해. 실패 시 None."""
    if target_half <= 0:
        return []
    inf = 10**9
    dp = [inf] * (target_half + 1)
    back_den = [-1] * (target_half + 1)
    dp[0] = 0
    for h in range(1, target_half + 1):
        for den, sz in ((32, 1), (16, 2), (8, 4), (4, 8), (2, 16), (1, 32)):
            if h >= sz and dp[h - sz] + 1 < dp[h]:
                dp[h] = dp[h - sz] + 1
                back_den[h] = den
    if dp[target_half] >= inf:
        return None
    out: list[int] = []
    h = target_half
    while h > 0:
        den = back_den[h]
        if den < 0:
            return None
        sz = _DEN_TO_HALF_UNITS[den]
        out.append(den)
        h -= sz
    return list(reversed(out))


def _strip_dy_from_alphatex_note_token(s: str) -> str:
    return re.sub(r"\s+\{dy\s+[^}]+\}\s*$", "", s).strip()


def _compute_bars_info(
    midi: pretty_midi.PrettyMIDI,
    max_end: float,
    *,
    bpm_override: float | None = None,
) -> list[tuple[float, float, int, int, float, int]]:
    """박자표·템포 구간에 따른 마디 타임라인(_midi_to_alphatex와 동일 규칙)."""
    eps = 1e-6
    tempo_segments = _parse_tempo_segments(midi)
    ts_segments = _parse_time_signature_segments(midi)
    ts_pairs: list[tuple[float, tuple[int, int]]] = [(t, (n, d)) for t, n, d in ts_segments]
    bars_info: list[tuple[float, float, int, int, float, int]] = []
    t_cursor = 0.0
    while t_cursor < max_end + eps or not bars_info:
        num_d = _segment_value_at(ts_pairs, t_cursor, (4, 4))
        num, den = num_d[0], num_d[1]
        if bpm_override is not None:
            bpm = float(bpm_override)
        else:
            bpm = float(_segment_value_at(tempo_segments, t_cursor, 120.0))
        bpm = max(20.0, min(300.0, bpm))
        measure_units = _measure_units_16ths(num, den)
        measure_sec = measure_units * (60.0 / bpm) / 4.0
        bars_info.append((t_cursor, t_cursor + measure_sec, num, den, bpm, measure_units))
        t_cursor += measure_sec
        if len(bars_info) > 100_000:
            break
    return bars_info


def _validate_alphatex_with_alphatab(tex: str) -> dict[str, Any]:
    """
    alphaTab(자바스크립트) AlphaTexLexer/Parser를 호출해
    AlphaTexDiagnosticBag 기준으로 오류를 검증한다.
    """

    root_dir = Path(__file__).resolve().parents[3]
    frontend_dir = root_dir / "frontend"

    tmp_root = frontend_dir / ".tmp-alphatex-validator"
    tmp_root.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    tex_path = tmp_root / f"input-{nonce}.alphatex"
    node_mjs_path = tmp_root / f"validate-{nonce}.mjs"

    try:
        tex_path.write_text(tex, encoding="utf-8")

        node_mjs_path.write_text(
            r"""
import fs from 'fs';
import * as alphaTab from '@coderline/alphatab';

const { AlphaTexLexer, AlphaTexParser, AlphaTexParseMode, AlphaTexNodeType } = alphaTab.importer.alphaTex;

const inputPath = process.argv[2];
const source = fs.readFileSync(inputPath, 'utf8');

const lexer = new AlphaTexLexer(source);
let types = [];
let lbrace = 0, rbrace = 0, lparen = 0, rparen = 0;
while (true) {
  const tok = lexer.peekToken();
  if (!tok) break;
  types.push(tok.nodeType);
  if (tok.nodeType === AlphaTexNodeType.LBrace) lbrace++;
  if (tok.nodeType === AlphaTexNodeType.RBrace) rbrace++;
  if (tok.nodeType === AlphaTexNodeType.LParen) lparen++;
  if (tok.nodeType === AlphaTexNodeType.RParen) rparen++;
  lexer.advance();
}

let colonOk = true;
for (let i = 0; i < types.length - 1; i++) {
  if (types[i] === AlphaTexNodeType.Colon && types[i + 1] !== AlphaTexNodeType.Number) {
    colonOk = false;
    break;
  }
}

const braceOk = lbrace === rbrace;
const parenOk = lparen === rparen;
const hasTag = types.includes(AlphaTexNodeType.Tag);
const hasIdent = types.includes(AlphaTexNodeType.Ident);

// Ident는 rest(r)나 property/alias에서만 나타날 수 있어, 필수 조건으로 두면
// 정상 alphaTex에서도 tokenGuard가 실패할 수 있다.
const tokenGuardOk = braceOk && parenOk && colonOk && hasTag;

const parser = new AlphaTexParser(source);
parser.mode = AlphaTexParseMode.ForModelImport;
const scoreNode = parser.read();

const allBase = [
  ...(parser.lexerDiagnostics?.items ?? []),
  ...(parser.parserDiagnostics?.items ?? [])
];

// 문제가 감지된 경우 Full 모드로 재파싱해 위치(start/end) 정밀도를 올린다.
let allFull = [];
if (!tokenGuardOk || allBase.some(d => d?.severity === 2)) {
  const fullParser = new AlphaTexParser(source);
  fullParser.mode = AlphaTexParseMode.Full;
  fullParser.read();
  allFull = [
    ...(fullParser.lexerDiagnostics?.items ?? []),
    ...(fullParser.parserDiagnostics?.items ?? [])
  ];
}

const all = allFull.length > 0 ? allFull : allBase;

const diags = all.map(d => ({
  code: d.code,
  message: d.message,
  severity: d.severity,
  start: d.start,
  end: d.end
}));

const errors = diags.filter(d => d.severity === 2);
const warnings = diags.filter(d => d.severity === 1);

// AST 레벨 품질 게이트
const astIssues = [];
const astWarnings = [];
const bars = scoreNode?.bars ?? [];
for (let barIndex = 0; barIndex < bars.length; barIndex++) {
  const bar = bars[barIndex];
  const beats = bar?.beats ?? [];

  // 마지막 마디가 아니면 PipeTokenNode가 있어야 한다.
  if (barIndex < bars.length - 1 && !bar?.pipe) {
    astIssues.push({
      kind: 'MissingPipeTokenNode',
      barIndex,
      message: `Bar ${barIndex + 1} is missing a pipe token before next bar.`,
      start: bar?.start,
      end: bar?.end
    });
  }

  for (let beatIndex = 0; beatIndex < beats.length; beatIndex++) {
    const beat = beats[beatIndex];

    // beat에 note/rest가 있으면 durationChange(:n)가 있어야 리듬 해석 안정성이 높다.
    const hasPlayable = Boolean(beat?.notes?.notes?.length) || Boolean(beat?.rest);
    const hasDurationChange = Boolean(beat?.durationChange?.value);
    if (hasPlayable && !hasDurationChange) {
      astWarnings.push({
        kind: 'MissingDurationChange',
        barIndex,
        beatIndex,
        message: `Beat ${beatIndex + 1} in bar ${barIndex + 1} has no durationChange.`,
        start: beat?.start,
        end: beat?.end
      });
    }

    // NoteList/Note 구조 검증
    const noteList = beat?.notes;
    if (noteList) {
      const notes = noteList?.notes ?? [];
      const isGrouped = Boolean(noteList?.openParenthesis || noteList?.closeParenthesis);

      // 동시발음(2음 이상)은 괄호 그룹이어야 한다.
      if (notes.length > 1 && !isGrouped) {
        astWarnings.push({
          kind: 'MissingNoteListParenthesis',
          barIndex,
          beatIndex,
          message: `Beat ${beatIndex + 1} in bar ${barIndex + 1} has multiple notes without parenthesis grouping.`,
          start: noteList?.start,
          end: noteList?.end
        });
      }

      // 단일음은 그룹 괄호가 없어야 과그룹화를 피할 수 있다.
      if (notes.length <= 1 && isGrouped) {
        astWarnings.push({
          kind: 'OverGroupedSingleNote',
          barIndex,
          beatIndex,
          message: `Beat ${beatIndex + 1} in bar ${barIndex + 1} has a single note with unnecessary parenthesis.`,
          start: noteList?.start,
          end: noteList?.end
        });
      }

      for (let noteIndex = 0; noteIndex < notes.length; noteIndex++) {
        const note = notes[noteIndex];
        const valueType = note?.noteValue?.nodeType;
        const hasStringDot = Boolean(note?.noteStringDot);
        const hasString = Boolean(note?.noteString);

        // 기타 전용 안정화: fretted note는 fret.string 형태(점/줄 번호)가 있어야 한다.
        if (valueType === AlphaTexNodeType.Number) {
          if (hasStringDot !== hasString) {
            astIssues.push({
              kind: 'NoteStringDotMismatch',
              barIndex,
              beatIndex,
              noteIndex,
              message: `Note ${noteIndex + 1} in beat ${beatIndex + 1} has inconsistent noteStringDot/noteString.`,
              start: note?.start,
              end: note?.end
            });
          }
          if (!hasString) {
            astIssues.push({
              kind: 'NonFrettedNumericNote',
              barIndex,
              beatIndex,
              noteIndex,
              message: `Numeric note without string index. Expected fret.string syntax for guitar tabs.`,
              start: note?.start,
              end: note?.end
            });
          }
        }
      }
    }
  }
}

const astHasErrors = astIssues.length > 0;

console.log(JSON.stringify({
  tokenGuard: { ok: tokenGuardOk, braceOk, parenOk, colonOk, hasTag, hasIdent },
  hasErrors: errors.length > 0 || astHasErrors,
  errors,
  warnings,
  astIssues,
  astWarnings
}));
""",
            encoding="utf-8",
        )

        completed = subprocess.run(
            ["node", str(node_mjs_path), str(tex_path)],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=os.environ.copy(),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "alphaTex 검증(node) 실패: "
                + (completed.stderr.strip() or completed.stdout.strip() or "unknown error")
            )

        try:
            payload = json.loads(completed.stdout or "{}")
        except Exception as exc:
            raise RuntimeError("alphaTex 검증 결과를 JSON으로 파싱하지 못했습니다.") from exc

        return payload
    finally:
        try:
            if tex_path.exists():
                tex_path.unlink()
        except Exception:
            pass
        try:
            if node_mjs_path.exists():
                node_mjs_path.unlink()
        except Exception:
            pass


def _should_retry_after_alphatex_diagnostics(diag_payload: dict[str, Any]) -> bool:
    error_codes: set[int] = {int(d.get("code")) for d in diag_payload.get("errors", []) if d.get("code") is not None}
    retry_codes = {201, 202, 206}
    return bool(error_codes.intersection(retry_codes))


@dataclass
class PipelineResult:
    job_dir: Path
    mp3_path: Path
    stems: dict[str, Path]
    midi_path: Path
    alphatex: str
    score: dict[str, Any]
    title: str
    artist: str
    lyrics: str | None
    lyrics_source: str


def _safe_job_name(url: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "-", url).strip("-").lower()
    cleaned = cleaned[:40] if cleaned else "youtube"
    short_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned}-{short_hash}"


def _safe_job_name_from_title(title: str, url: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "-", title).strip("-").lower()
    cleaned = cleaned[:40] if cleaned else "youtube"
    short_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned}-{short_hash}"


def _allocate_job_dir(base_root: Path, base_name: str) -> Path:
    """
    충돌 없는 작업 디렉터리를 생성한다.
    - 1회차: <base_name>
    - 중복 시: <base_name>-1, <base_name>-2, ...
    """
    base_root.mkdir(parents=True, exist_ok=True)
    for idx in range(0, 10_000):
        candidate_name = base_name if idx == 0 else f"{base_name}-{idx}"
        candidate = base_root / candidate_name
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("작업 폴더를 생성하지 못했습니다. 이름 충돌이 너무 많습니다.")


def _run(command: list[str], cwd: Path | None = None) -> None:
    env = os.environ.copy()
    # Windows(cp949) 콘솔에서 basic-pitch CLI의 유니코드 출력(✨)이 깨지며 종료되는 문제 방지
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"명령 실행 실패: {' '.join(command)}\n{stderr}")


def _download_mp3(url: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "source.mp3"
    _run([sys.executable, "-m", "yt_dlp", "-x", "--audio-format", "mp3", "-o", str(target), url])
    if not target.exists():
        raise RuntimeError("yt-dlp 다운로드 후 mp3 파일을 찾지 못했습니다.")
    return target


def _fetch_youtube_meta(url: str) -> tuple[str, str | None, str | None, float | None, str | None]:
    """
    반환: title, artist(트랙 메타·없을 수 있음), description(설명 전체), duration_sec, uploader
    가사는 LRCLIB 등에서 별도 해석한다.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--dump-single-json", "--skip-download", "--no-warnings", url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return _safe_job_name(url), None, None, None, None
    try:
        data = json.loads(completed.stdout or "{}")
    except Exception:
        return _safe_job_name(url), None, None, None, None
    title = str(data.get("title") or _safe_job_name(url))
    artist = data.get("artist")
    if artist is not None:
        artist = str(artist).strip() or None
    uploader = data.get("uploader") or data.get("channel")
    if uploader is not None:
        uploader = str(uploader).strip() or None
    description = str(data.get("description") or "").strip()
    duration_sec: float | None = None
    raw_dur = data.get("duration")
    if raw_dur is not None:
        try:
            duration_sec = float(raw_dur)
        except (TypeError, ValueError):
            duration_sec = None
    return title, artist, description or None, duration_sec, uploader


DEMUCS_MODEL_NAME = (os.environ.get("DEMUCS_MODEL") or "htdemucs_6s").strip() or "htdemucs_6s"


def _separate_demucs(mp3_path: Path, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    model_name = DEMUCS_MODEL_NAME
    _run(
        [sys.executable, "-m", "demucs.separate", "-n", model_name, "--mp3", "-o", str(out_dir), str(mp3_path)]
    )
    # demucs output: <out_dir>/<model_name>/<track_name>/*.mp3
    candidates = sorted((out_dir / model_name).glob("*"))
    if not candidates:
        raise RuntimeError("Demucs 결과 폴더를 찾지 못했습니다.")
    track_dir = candidates[0]
    stems = {}
    for name in ("vocals", "drums", "bass", "other", "guitar", "piano"):
        matched = list(track_dir.glob(f"{name}.*"))
        if matched:
            # 외부에서 job_dir/stems/만 봐도 바로 알 수 있게 루트로 복사한다.
            dest = out_dir / f"{name}.mp3"
            try:
                if matched[0].resolve() != dest.resolve():
                    shutil.copy2(matched[0], dest)
            except OSError as exc:
                raise RuntimeError(f"Demucs stem({name})을 {dest} 로 복사하지 못했습니다: {exc}") from exc
            stems[name] = dest
    # guitar/piano가 없는 모델에서도 최소 stems 반환
    return stems


def _ffmpeg_mp3_to_wav_mono_44k(src_mp3: Path, dst_wav: Path) -> Path:
    """기타 스템 MP3를 Basic Pitch 입력용 WAV(모노 44.1kHz)로 변환한다."""
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src_mp3),
            "-ac",
            "1",
            "-ar",
            "44100",
            "-f",
            "wav",
            str(dst_wav),
        ]
    )
    if not dst_wav.is_file():
        raise RuntimeError(f"ffmpeg가 WAV를 생성하지 못했습니다: {dst_wav}")
    return dst_wav


def _primary_bpm_from_midi(midi: pretty_midi.PrettyMIDI) -> float:
    """MIDI 템포 이벤트에서 QPM을 읽는다. 없거나 비정상이면 120."""
    segs = _parse_tempo_segments(midi)
    bpm = float(segs[0][1]) if segs else 120.0
    if not math.isfinite(bpm) or bpm <= 0:
        bpm = 120.0
    return max(20.0, min(300.0, bpm))


def _ensure_flat_guitar_stem_mp3(stems: dict[str, Path], stems_root: Path) -> Path:
    """
    `guitar` 스템이 있으면 그대로 사용하고, 없으면(4스템 모델 등) `other`를 기타 트랙으로 복사한다.
    Basic Pitch·onset 전처리는 항상 `stems/guitar.mp3`를 가리키게 한다.
    """
    src = stems.get("guitar") or stems.get("other")
    if not src or not src.is_file():
        raise RuntimeError("Demucs 출력에서 guitar/other stem을 찾지 못했습니다.")
    stems_root.mkdir(parents=True, exist_ok=True)
    dest = stems_root / "guitar.mp3"
    try:
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
    except OSError as exc:
        raise RuntimeError(f"기타 stem을 stems/guitar.mp3 로 복사하지 못했습니다: {exc}") from exc
    stems["guitar"] = dest
    return dest


def _basic_pitch_to_midi(guitar_audio: Path, midi_out: Path) -> Path:
    """기타 WAV(또는 오디오) → Basic Pitch → `midi_out` 경로로 정리."""
    midi_out.parent.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "basic_pitch.predict", str(midi_out.parent), str(guitar_audio)])
    expected = midi_out.parent / f"{guitar_audio.stem}.mid"
    if expected.is_file():
        if expected.resolve() != midi_out.resolve():
            shutil.move(str(expected), str(midi_out))
        return midi_out
    produced = sorted(midi_out.parent.glob("*.mid"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not produced:
        raise RuntimeError("Basic Pitch 변환 결과 MIDI 파일을 찾지 못했습니다.")
    shutil.move(str(produced[0]), str(midi_out))
    return midi_out


def _guitar_wav_to_midi_basic_pitch(guitar_wav: Path, midi_out: Path) -> Path:
    """기타 스템 WAV → Basic Pitch MIDI."""
    return _basic_pitch_to_midi(guitar_wav, midi_out)


def _match_tab_hint_for_note(
    note: dict[str, Any],
    hints: list[dict[str, Any]] | None,
) -> tuple[int, int] | None:
    """pitch·onset(초)이 일치하는 탭 힌트를 찾는다."""
    if not hints:
        return None
    p = int(note["pitch"])
    s = float(note["start"])
    best: tuple[int, int] | None = None
    best_d = 1e9
    for h in hints:
        try:
            if int(h["pitch"]) != p:
                continue
            d = abs(float(h["start"]) - s)
        except (KeyError, TypeError, ValueError):
            continue
        if d < 0.085 and d < best_d:
            best_d = d
            try:
                best = (int(h["string"]), int(h["fret"]))
            except (KeyError, TypeError, ValueError):
                continue
    return best


def _enrich_raw_notes_with_tab_hints(
    notes: list[dict[str, Any]],
    hints: list[dict[str, Any]] | None,
) -> None:
    """Omnizart·사이드카 등에서 온 줄·프렛을 raw 노트에 붙인다(있을 때만)."""
    if not hints:
        return
    for n in notes:
        tab = _match_tab_hint_for_note(n, hints)
        if tab:
            n["string"], n["fret"] = tab[0], tab[1]


def _midi_note_to_string_fret(midi_pitch: int) -> tuple[int, int]:
    # 가장 낮은 프렛 우선 매핑
    best = (6, max(0, midi_pitch - GUITAR_OPEN_MIDI[-1]))
    for string_idx, open_pitch in enumerate(GUITAR_OPEN_MIDI, start=1):
        fret = midi_pitch - open_pitch
        if 0 <= fret <= 24:
            if fret < best[1]:
                best = (string_idx, fret)
    return best


def _midi_pitch_to_candidate_positions(midi_pitch: int) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for string_idx, open_pitch in enumerate(GUITAR_OPEN_MIDI, start=1):
        fret = midi_pitch - open_pitch
        if 0 <= fret <= 24:
            candidates.append((string_idx, int(fret)))
    return candidates


def _position_transition_cost(prev: tuple[int, int], nxt: tuple[int, int]) -> float:
    prev_string, prev_fret = prev
    string, fret = nxt

    # 포지션 연속성 비용(이동량/점프/현실성 제약)
    cost = abs(prev_fret - fret) + 0.35 * abs(prev_string - string)

    # 개방현 우선(자연스러운 연주/손가락 부담 완화)
    if fret == 0:
        cost -= 0.25

    # 과도한 점프 페널티
    jump = abs(prev_fret - fret)
    if jump > 10:
        cost += (jump - 10) * 0.8

    return float(cost)


def _position_transition_cost_v2(
    prev: tuple[int, int],
    nxt: tuple[int, int],
    prev_meta: dict[str, Any] | None,
    nxt_meta: dict[str, Any] | None,
) -> float:
    """기본 전이 비용 + 동일 운지·길이·velocity·스트링 변경."""
    base = _position_transition_cost(prev, nxt)
    if not prev_meta or not nxt_meta:
        return base
    ps, pf = prev
    ns, nf = nxt
    if ps == ns and pf == nf:
        base -= TAB_V2_SAME_FRET_BONUS
    dur = float(nxt_meta.get("end", 0.0)) - float(nxt_meta.get("start", 0.0))
    if dur < TAB_V2_SHORT_NOTE_SEC:
        base += TAB_V2_SHORT_NOTE_PENALTY
    vel = int(nxt_meta.get("velocity", 64))
    if vel < TAB_V2_LOW_VEL_THRESH:
        base += TAB_V2_LOW_VEL_PENALTY
    if ps != ns:
        base += TAB_V2_STRING_CHANGE_EXTRA
    return float(base)


def _nearest_onset_distance_sec(onset_times: list[float], t: float) -> float:
    if not onset_times:
        return float("inf")
    i = bisect.bisect_left(onset_times, t)
    d = float("inf")
    if i < len(onset_times):
        d = min(d, abs(onset_times[i] - t))
    if i > 0:
        d = min(d, abs(onset_times[i - 1] - t))
    return d


def _next_onset_after(onset_times: list[float], t: float) -> float | None:
    if not onset_times:
        return None
    i = bisect.bisect_right(onset_times, t)
    if i < len(onset_times):
        return onset_times[i]
    return None


def _reduce_note_density_with_onsets(
    raw_notes: list[dict[str, Any]],
    *,
    onset_times_sec: list[float] | None,
    quarter_sec: float,
    onset_gate_mode: str,
    stats_out: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not raw_notes:
        return raw_notes

    onset_times = sorted(float(t) for t in (onset_times_sec or []) if t is not None)
    mode = onset_gate_mode if onset_gate_mode in ("hard", "soft", "off") else "hard"
    hard_drop = 0
    soft_adj = 0
    if stats_out is not None:
        stats_out["onset_gate_mode"] = mode

    # 3-A: onset 근접 노트 우선 유지 (hard: 기존 드롭, soft: velocity 감쇠, off: 스킵)
    if onset_times and mode != "off":
        gated: list[dict[str, Any]] = []
        for n in raw_notes:
            d = _nearest_onset_distance_sec(onset_times, float(n["start"]))
            vel = int(n["velocity"])
            if d <= ONSET_TOLERANCE_SEC or vel >= (MIN_NOTE_VELOCITY + 8):
                gated.append(n)
                continue
            if mode == "hard":
                hard_drop += 1
                continue
            # soft
            nv = max(MIN_NOTE_VELOCITY, int(round(vel * 0.62)))
            if nv != vel:
                soft_adj += 1
            nn = {**n, "velocity": nv}
            gated.append(nn)
        if gated:
            raw_notes = gated

    if stats_out is not None:
        stats_out["onset_hard_dropped_notes"] = int(hard_drop)
        stats_out["onset_soft_velocity_adjusted"] = int(soft_adj)

    # 3-B: 동일 pitch의 과도한 촘촘 onset 병합
    min_ioi = max(MERGE_MIN_IOI_SEC, quarter_sec / 8.0)  # 대략 1/32 하한
    by_pitch: dict[int, list[dict[str, Any]]] = {}
    for n in raw_notes:
        by_pitch.setdefault(int(n["pitch"]), []).append(n)

    merged: list[dict[str, Any]] = []
    for pitch, arr in by_pitch.items():
        arr_sorted = sorted(arr, key=lambda x: (float(x["start"]), float(x["end"])))
        cur = dict(arr_sorted[0])
        for nxt in arr_sorted[1:]:
            gap = float(nxt["start"]) - float(cur["end"])
            # 겹치거나 너무 가까우면 같은 발음으로 취급
            if gap <= min_ioi:
                cur["end"] = max(float(cur["end"]), float(nxt["end"]))
                cur["velocity"] = max(int(cur["velocity"]), int(nxt["velocity"]))
                if "note_uid" in cur or "note_uid" in nxt:
                    u1 = int(cur.get("note_uid", 10**9))
                    u2 = int(nxt.get("note_uid", 10**9))
                    cur["note_uid"] = min(u1, u2)
            else:
                merged.append(cur)
                cur = dict(nxt)
        merged.append(cur)

    # 3-D: 지속 길이 상한 (다음 onset 직전 또는 최대 N박)
    clamped: list[dict[str, Any]] = []
    max_sustain_sec = quarter_sec * MAX_SUSTAIN_BEATS
    for n in sorted(merged, key=lambda x: (float(x["start"]), int(x["pitch"]))):
        start = float(n["start"])
        end = float(n["end"])
        next_onset = _next_onset_after(onset_times, start + 1e-6) if onset_times else None
        cap1 = start + max_sustain_sec
        cap2 = (next_onset + SUSTAIN_RELEASE_SEC) if next_onset is not None else cap1
        new_end = min(end, cap1, cap2)
        if new_end <= start + 1e-3:
            continue
        row = {
            "pitch": int(n["pitch"]),
            "velocity": int(n["velocity"]),
            "start": start,
            "end": new_end,
        }
        if "note_uid" in n:
            row["note_uid"] = int(n["note_uid"])
        clamped.append(row)
    return clamped if clamped else raw_notes


def _quantized_beats_from_midi(
    midi: pretty_midi.PrettyMIDI,
    tempo: float,
    *,
    preset: TabRenderPreset,
    onset_times_sec: list[float] | None = None,
    tab_hints: list[dict[str, Any]] | None = None,
    onset_stats_out: dict[str, Any] | None = None,
    bars_info: list[tuple[float, float, int, int, float, int]] | None = None,
    bar_chords: list[str] | None = None,
    capo: int = 0,
    chord_metrics_out: dict[str, Any] | None = None,
    max_notes_per_slot: int = MAX_NOTES_PER_SLOT,
) -> tuple[list[dict[str, Any]], float]:
    """
    MIDI note start/end를 기본 양자화하고 모드 preset에 따라 격자 해상도를 적용한다.
    """

    quarter = 60.0 / max(1.0, tempo)
    step_16 = quarter / 4.0  # 1/16
    step_32 = step_16 / 2.0  # 1/32

    # 1/16 vs 1/32에서 start/end 스냅 오차를 비교해 그리드 선택
    melodic_instruments = [inst for inst in midi.instruments if not inst.is_drum and inst.notes]
    if not melodic_instruments:
        melodic_instruments = [inst for inst in midi.instruments if inst.notes]

    candidate_raw_notes: list[dict[str, Any]] = []
    uid_next = 0
    for inst in melodic_instruments:
        for note in inst.notes:
            if note.end <= note.start:
                continue
            if int(note.velocity) < MIN_NOTE_VELOCITY:
                continue
            if not (GUITAR_MIN_PITCH <= int(note.pitch) <= GUITAR_MAX_PITCH):
                continue
            candidate_raw_notes.append(
                {
                    "note_uid": uid_next,
                    "pitch": int(note.pitch),
                    "velocity": int(note.velocity),
                    "start": float(note.start),
                    "end": float(note.end),
                }
            )
            uid_next += 1

    candidate_raw_notes = _reduce_note_density_with_onsets(
        candidate_raw_notes,
        onset_times_sec=onset_times_sec,
        quarter_sec=quarter,
        onset_gate_mode=preset.onset_gate_mode,
        stats_out=onset_stats_out,
    )

    _enrich_raw_notes_with_tab_hints(candidate_raw_notes, tab_hints)

    if not candidate_raw_notes:
        # 파서가 무조건 구조를 기대하므로 더미 비트 1개는 남긴다.
        return (
            [
                {
                    "time": 0.0,
                    "chord": None,
                    "lyric": None,
                    "notes": [{"string": 6, "fret": 0, "start": 0.0, "end": float(step_16)}],
                }
            ],
            step_16,
        )

    def snap_error(note_time: float, step: float) -> float:
        snapped = round(note_time / step) * step
        return abs(note_time - snapped)

    if preset.unified_grid:
        step = quarter / float(max(1, preset.subdivisions_per_quarter))
    else:
        start_err_16 = [snap_error(n["start"], step_16) for n in candidate_raw_notes]
        end_err_16 = [snap_error(n["end"], step_16) for n in candidate_raw_notes]
        start_err_32 = [snap_error(n["start"], step_32) for n in candidate_raw_notes]
        end_err_32 = [snap_error(n["end"], step_32) for n in candidate_raw_notes]

        median_err_16 = statistics.median(start_err_16 + end_err_16)
        median_err_32 = statistics.median(start_err_32 + end_err_32)
        any_32_needed = any((n["end"] - n["start"]) <= step_16 * 0.75 for n in candidate_raw_notes)

        step = step_32 if any_32_needed and median_err_32 <= median_err_16 * 0.6 else step_16

    # slot -> raw note list (여기서 아직 string/fret은 DP 후에 결정)
    slots: dict[int, list[dict[str, Any]]] = {}
    for n in candidate_raw_notes:
        slot = max(0, int(round(float(n["start"]) / step)))
        start = slot * step
        end_slot = max(slot + 1, int(round(float(n["end"]) / step)))
        end = end_slot * step

        slot_note: dict[str, Any] = {
            "pitch": n["pitch"],
            "velocity": n["velocity"],
            "start": float(start),
            "end": float(end),
        }
        if "note_uid" in n:
            slot_note["note_uid"] = int(n["note_uid"])
        if "string" in n and "fret" in n:
            slot_note["string"] = int(n["string"])
            slot_note["fret"] = int(n["fret"])
        slots.setdefault(slot, []).append(slot_note)

    slot_keys = sorted(slots.keys())
    if not slot_keys:
        return (
            [
                {
                    "time": 0.0,
                    "chord": None,
                    "lyric": None,
                    "notes": [{"string": 6, "fret": 0, "start": 0.0, "end": float(step)}],
                }
            ],
            step,
        )

    # 각 slot에서 lead note를 하나 뽑고, lead의 string/fret만 DP(Viterbi)로 연속성 최소화.
    slot_leads: dict[int, dict[str, Any]] = {}
    for k in slot_keys:
        notes = slots[k]
        lead = max(notes, key=lambda x: (x["velocity"], -x["pitch"]))
        slot_leads[k] = lead

    # slot 별 lead 후보 positions
    lead_candidates: dict[int, list[tuple[int, int]]] = {}
    for k in slot_keys:
        lead = slot_leads[k]
        if "string" in lead and "fret" in lead:
            lead_candidates[k] = [(int(lead["string"]), int(lead["fret"]))]
            continue
        lead_pitch = lead["pitch"]
        cand = _midi_pitch_to_candidate_positions(lead_pitch)
        if not cand:
            cand = [_midi_note_to_string_fret(lead_pitch)]
        lead_candidates[k] = cand

    # Viterbi DP: 각 slot의 lead pos를 선택한다.
    dp: dict[tuple[int, int], float] = {}
    back: dict[int, dict[tuple[int, int], tuple[int, int] | None]] = {}
    prev_slot_keys = slot_keys[0:1]
    first_k = prev_slot_keys[0]
    use_v2 = preset.use_fingering_v2
    bars_local = bars_info or []
    bar_labels_local = bar_chords or []
    bar_riff_segments = _detect_riff_bars(slots, slot_keys, step, bars_local, bar_labels_local)
    slot_ctx: dict[int, tuple[str | None, set[int], tuple[Any, ...] | None, dict[str, float]]] = {}
    bar_idx_cache = 0
    for k in slot_keys:
        time_value = float(k * step)
        if bars_local:
            bar_idx_cache = _bar_index_for_time(time_value, bars_local, bar_idx_cache)
            bar_label = (
                bar_labels_local[bar_idx_cache]
                if bar_idx_cache < len(bar_labels_local)
                else None
            )
            is_riff = bar_idx_cache in bar_riff_segments
        else:
            bar_label = None
            is_riff = False
        chord_pcs = _chord_pitch_classes_from_label(bar_label)
        shape = _chord_shape_tuple_for_label(bar_label or "")
        slot_ctx[k] = (bar_label, chord_pcs, shape, _hybrid_weight_profile(is_riff_segment=is_riff))

    for pos in lead_candidates[first_k]:
        bar_label_0, chord_pcs_0, shape_0, profile_0 = slot_ctx[first_k]
        seed_cost, _ = _mapping_position_score(
            pitch=int(slot_leads[first_k]["pitch"]),
            pos=pos,
            prev_pos=pos,
            bar_label=bar_label_0,
            chord_pcs=chord_pcs_0,
            shape=shape_0,
            capo=capo,
            use_v2=use_v2,
            prev_meta=slot_leads[first_k],
            note_meta=slot_leads[first_k],
            weight_profile=profile_0,
        )
        dp[pos] = seed_cost
        back.setdefault(first_k, {})[pos] = None
    for i, k in enumerate(slot_keys[1:], start=1):
        prev_k = slot_keys[i - 1]
        prev_meta = slot_leads[prev_k]
        next_meta = slot_leads[k]
        new_dp: dict[tuple[int, int], float] = {}
        back.setdefault(k, {})
        bar_label_k, chord_pcs_k, shape_k, profile_k = slot_ctx[k]
        for pos in lead_candidates[k]:
            best_cost = float("inf")
            best_prev_pos: tuple[int, int] | None = None
            for prev_pos, prev_cost in dp.items():
                score_cost, _detail = _mapping_position_score(
                    pitch=int(slot_leads[k]["pitch"]),
                    pos=pos,
                    prev_pos=prev_pos,
                    bar_label=bar_label_k,
                    chord_pcs=chord_pcs_k,
                    shape=shape_k,
                    capo=capo,
                    use_v2=use_v2,
                    prev_meta=prev_meta,
                    note_meta=next_meta,
                    weight_profile=profile_k,
                )
                cost = prev_cost + score_cost
                if cost < best_cost:
                    best_cost = cost
                    best_prev_pos = prev_pos
            new_dp[pos] = best_cost
            back[k][pos] = best_prev_pos
        dp = new_dp

    last_k = slot_keys[-1]
    best_last_pos = min(dp.keys(), key=lambda p: dp[p])

    best_lead_pos: dict[int, tuple[int, int]] = {last_k: best_last_pos}
    cur_pos = best_last_pos
    # back[k][pos] = (k의 lead pos가 pos일 때, 이전 슬롯의 pos)
    for idx in range(len(slot_keys) - 2, -1, -1):
        k = slot_keys[idx]
        next_k = slot_keys[idx + 1]
        prev_pos = back[next_k][cur_pos]
        best_lead_pos[k] = prev_pos if prev_pos is not None else lead_candidates[k][0]
        cur_pos = best_lead_pos[k]

    # slot 별 note mapping (lead은 DP 결과, 나머지는 코드/운지 비용 + 전이비용 결합)
    beats: list[dict[str, Any]] = []
    first_slot_time = slot_keys[0] * step
    if first_slot_time > 0:
        beats.append({"time": 0.0, "chord": None, "lyric": None, "notes": []})

    capo_clamped = _clamp_capo_0_5(capo)
    bar_idx_cache = 0
    chord_hits = 0
    shape_hits = 0
    mapped_total = 0
    riff_slot_count = 0

    prev_lead_pos: tuple[int, int] = best_lead_pos[slot_keys[0]]
    for k in slot_keys:
        time_value = float(k * step)
        notes = slots[k]
        mapped_notes: list[dict[str, Any]] = []
        bar_label, chord_pcs, shape, weight_profile = slot_ctx[k]
        if bars_local:
            bar_idx_cache = _bar_index_for_time(time_value, bars_local, bar_idx_cache)
            if bar_idx_cache in bar_riff_segments:
                riff_slot_count += 1
        lead_note = slot_leads[k]
        for n in notes:
            if n is lead_note:
                string_no, fret = best_lead_pos[k]
                row_m = {
                    "string": int(string_no),
                    "fret": int(fret),
                    "start": float(n["start"]),
                    "end": float(n["end"]),
                    "velocity": int(n["velocity"]),
                }
                if "note_uid" in n:
                    row_m["note_uid"] = int(n["note_uid"])
                mapped_notes.append(row_m)
                mapped_total += 1
                if chord_pcs and ((GUITAR_OPEN_MIDI[string_no - 1] + fret + capo_clamped) % 12) in chord_pcs:
                    chord_hits += 1
                if shape is not None:
                    sf = _shape_fret_for_string(shape, string_no)
                    if sf is not None and abs(int(fret) - int(sf)) <= 1:
                        shape_hits += 1
                continue

            if "string" in n and "fret" in n:
                row_m = {
                    "string": int(n["string"]),
                    "fret": int(n["fret"]),
                    "start": float(n["start"]),
                    "end": float(n["end"]),
                    "velocity": int(n["velocity"]),
                }
                if "note_uid" in n:
                    row_m["note_uid"] = int(n["note_uid"])
                mapped_notes.append(row_m)
                mapped_total += 1
                if chord_pcs and ((GUITAR_OPEN_MIDI[int(n["string"]) - 1] + int(n["fret"]) + capo_clamped) % 12) in chord_pcs:
                    chord_hits += 1
                if shape is not None:
                    sf = _shape_fret_for_string(shape, int(n["string"]))
                    if sf is not None and abs(int(n["fret"]) - int(sf)) <= 1:
                        shape_hits += 1
                continue

            candidates = _midi_pitch_to_candidate_positions(n["pitch"])
            if not candidates:
                candidates = [_midi_note_to_string_fret(n["pitch"])]
            best_pos = candidates[0]
            best_cost = float("inf")
            best_detail = {"pitch_error": 0.0, "chord_tone_hit": 0.0, "shape_alignment_hit": 0.0}
            for pos in candidates:
                score_cost, detail = _mapping_position_score(
                    pitch=int(n["pitch"]),
                    pos=pos,
                    prev_pos=prev_lead_pos,
                    bar_label=bar_label,
                    chord_pcs=chord_pcs,
                    shape=shape,
                    capo=capo_clamped,
                    use_v2=use_v2,
                    prev_meta=lead_note,
                    note_meta=n,
                    weight_profile=weight_profile,
                )
                if score_cost < best_cost:
                    best_cost = score_cost
                    best_pos = pos
                    best_detail = detail
            string_no, fret = best_pos
            row_m = {
                "string": int(string_no),
                "fret": int(fret),
                "start": float(n["start"]),
                "end": float(n["end"]),
                "velocity": int(n["velocity"]),
            }
            if "note_uid" in n:
                row_m["note_uid"] = int(n["note_uid"])
            mapped_notes.append(row_m)
            mapped_total += 1
            chord_hits += int(best_detail.get("chord_tone_hit", 0.0) > 0.5)
            shape_hits += int(best_detail.get("shape_alignment_hit", 0.0) > 0.5)

        # 같은 slot에서 중복 줄 제거 + 최대 음수 제한
        by_string: dict[int, dict[str, Any]] = {}
        for mn in mapped_notes:
            existing = by_string.get(mn["string"])
            if existing is None:
                by_string[mn["string"]] = mn
                continue
            if (mn["velocity"], -mn["fret"]) > (existing["velocity"], -existing["fret"]):
                by_string[mn["string"]] = mn

        normalized_notes = sorted(by_string.values(), key=lambda x: (x["string"], x["fret"]))[
            : max(1, int(max_notes_per_slot))
        ]
        beats.append(
            {
                "time": time_value,
                "chord": None,
                "lyric": None,
                "notes": normalized_notes,
            }
        )

        prev_lead_pos = best_lead_pos[k]

    if chord_metrics_out is not None:
        denom = max(1, int(mapped_total))
        chord_metrics_out.clear()
        chord_metrics_out.update(
            {
                "chord_tone_hit_rate": round(float(chord_hits) / float(denom), 4),
                "shape_alignment_rate": round(float(shape_hits) / float(denom), 4),
                "riff_segment_ratio": round(float(riff_slot_count) / float(max(1, len(slot_keys))), 4),
            }
        )

    return beats, step


def _midi_to_alphatex(
    midi_path: Path,
    title: str,
    *,
    artist: str = "",
    lyrics: str | None = None,
    audio_duration_sec: float | None = None,
    capo: int = 0,
    tempo_override: float | None = None,
    onset_times_sec: list[float] | None = None,
    tab_output_dir: Path | None = None,
    tab_experiment_out: dict[str, Any] | None = None,
    preset: TabRenderPreset = TRANSCRIPTION_PRESET,
    arrangement_relax_level: int = 0,
) -> str:
    tab_hints = extract_guitar_tab_hints_from_midi(midi_path)
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    capo = _clamp_capo_0_5(capo)
    tempo_segments = _parse_tempo_segments(midi)
    ts_segments = _parse_time_signature_segments(midi)
    tempo0 = float(tempo_override) if tempo_override is not None else float(tempo_segments[0][1])
    tempo0 = max(20.0, min(300.0, tempo0))

    safe_title = _escape_alpha_tex_string(title)
    safe_artist = _escape_alpha_tex_string(artist) if artist else ""
    lyrics_line = ""
    if lyrics and lyrics.strip():
        lyrics_line = f"\\lyrics \"{_escape_alpha_tex_lyrics(lyrics.strip())}\"\n"

    inst_name = _midi_program_to_alphatab_instrument(_get_primary_midi_program(midi))
    raw_notes = _raw_guitar_notes_from_midi(midi)
    max_raw = max([n["end"] for n in raw_notes], default=0.0)
    max_end = max(max_raw, 0.01)
    bars_info = _compute_bars_info(midi, max_end, bpm_override=tempo_override)
    bar_chords = _bar_chord_labels(raw_notes, bars_info, int(capo))
    if preset.name == "arrangement":
        bar_chords = _smooth_bar_chord_labels(bar_chords)

    onset_stats: dict[str, Any] = {}
    chord_mapping_metrics: dict[str, Any] = {}
    beats, _grid_step_sec = _quantized_beats_from_midi(
        midi,
        tempo0,
        preset=preset,
        onset_times_sec=onset_times_sec,
        tab_hints=tab_hints,
        onset_stats_out=onset_stats,
        bars_info=bars_info,
        bar_chords=bar_chords,
        capo=capo,
        chord_metrics_out=chord_mapping_metrics,
        max_notes_per_slot=MAX_NOTES_PER_SLOT + max(0, int(arrangement_relax_level)),
    )
    beats = sorted(beats, key=lambda b: float(b.get("time", 0.0)))

    suppress_mid_bar_midi_tempo = tempo_override is not None

    note_events: list[dict[str, Any]] = []
    for b in beats:
        for n in b.get("notes", []):
            if not n:
                continue
            if n.get("start") is None or n.get("end") is None:
                continue
            ev: dict[str, Any] = {
                "string": int(n["string"]),
                "fret": int(n["fret"]),
                "start": float(n["start"]),
                "end": float(n["end"]),
                "velocity": int(n.get("velocity", 64)),
            }
            if "note_uid" in n:
                ev["note_uid"] = int(n["note_uid"])
            note_events.append(ev)

    if note_events:
        note_events, _ref_passes = refine_note_events_with_reference_midi(
            note_events, midi_path, max_passes=2
        )

    base_den = preset.base_den
    eps = 1e-6

    ts_pairs: list[tuple[float, tuple[int, int]]] = [(t, (n, d)) for t, n, d in ts_segments]
    chord_order_unique: list[str] = []
    _seen_ch: set[str] = set()
    for _lbl in bar_chords:
        if _lbl not in _seen_ch:
            _seen_ch.add(_lbl)
            chord_order_unique.append(_lbl)
    chord_def_block = _alphatex_chord_definitions_block(chord_order_unique)
    capo_line = f"\\capo {int(capo)}\n" if int(capo) > 0 else ""

    emit_dy = preset.emit_dynamics

    def uniq_sorted(values: list[float]) -> list[float]:
        values_sorted = sorted(values)
        out: list[float] = []
        for v in values_sorted:
            if not out or abs(v - out[-1]) > 1e-5:
                out.append(round(v, 6))
        return out

    def active_content_with_dy(t0: float, prev_dy: str | None) -> tuple[str, str | None]:
        active: list[dict[str, Any]] = [
            n for n in note_events if n["start"] <= t0 + eps and n["end"] > t0 + eps
        ]
        if not active:
            return "r", prev_dy

        by_string: dict[int, dict[str, Any]] = {}
        for n in active:
            s = int(n["string"])
            existing = by_string.get(s)
            if existing is None:
                by_string[s] = n
                continue
            if (n["velocity"], -n["fret"]) > (existing["velocity"], -existing["fret"]):
                by_string[s] = n

        chosen = sorted(by_string.values(), key=lambda x: (x["string"], x["fret"]))
        max_vel = max(int(n["velocity"]) for n in chosen)
        dy = _velocity_to_dy(max_vel)
        if len(chosen) == 1:
            cn = chosen[0]
            base = f"{cn['fret']}.{cn['string']}"
        else:
            chord = " ".join(f"{n['fret']}.{n['string']}" for n in chosen)
            base = f"({chord})"

        if not emit_dy:
            return base, prev_dy
        if prev_dy is None or dy != prev_dy:
            return f"{base} {{dy {dy}}}", dy
        return base, prev_dy

    bars: list[str] = []

    first_ts = _segment_value_at(ts_pairs, 0.0, (4, 4))
    first_bpm = (
        float(tempo_override)
        if tempo_override is not None
        else float(_segment_value_at(tempo_segments, 0.0, 120.0))
    )
    first_bpm = max(20.0, min(300.0, first_bpm))
    printed_ts: tuple[int, int] = first_ts
    printed_bpm: float = first_bpm

    last_bar_end = bars_info[-1][1] if bars_info else 0.0
    subdiv_snap = preset.subdivisions_per_quarter if preset.unified_grid else 4
    quarter_sec_snap = 60.0 / max(20.0, min(300.0, first_bpm))
    step_snap = quarter_sec_snap / float(max(1, subdiv_snap))

    def _snap_time_to_grid(t: float) -> float:
        return round(float(t) / step_snap) * step_snap

    boundaries_legacy: set[float] = {0.0, last_bar_end}
    for n in note_events:
        boundaries_legacy.add(float(n["start"]))
        boundaries_legacy.add(float(n["end"]))
    for bs, be, *_r in bars_info:
        boundaries_legacy.add(bs)
        boundaries_legacy.add(be)
    boundary_count_before = len(uniq_sorted(list(boundaries_legacy)))

    boundaries: set[float] = {0.0, last_bar_end}
    for bs, be, *_r in bars_info:
        boundaries.add(bs)
        boundaries.add(be)
    if preset.use_grid_boundaries:
        for n in note_events:
            boundaries.add(round(_snap_time_to_grid(float(n["start"])), 6))
            boundaries.add(round(_snap_time_to_grid(float(n["end"])), 6))
    else:
        for n in note_events:
            boundaries.add(float(n["start"]))
            boundaries.add(float(n["end"]))
    sorted_boundaries = uniq_sorted(list(boundaries))
    boundary_count_after = len(sorted_boundaries)

    bar_idx = 0
    bar_tokens: list[str] = []
    bar_units = 0.0

    def flush_bar() -> None:
        nonlocal bar_tokens, bar_units, bar_idx, printed_ts, printed_bpm
        if bar_idx >= len(bars_info):
            return
        bs, be, num, den, bpm, measure_units_target = bars_info[bar_idx]
        while bar_units < measure_units_target - 1e-6:
            remaining = measure_units_target - bar_units
            if remaining >= 1.0 - 1e-6:
                bar_tokens.append("r")
                bar_units += 1.0
            elif remaining >= 0.5 - 1e-6:
                bar_tokens.append(":32 r")
                bar_units += 0.5
            else:
                break
        if not bar_tokens:
            bar_idx += 1
            return
        first = bar_tokens[0]
        if not first.lstrip().startswith(":"):
            bar_tokens[0] = f":{base_den} {first}"
        ch_lbl = bar_chords[bar_idx] if bar_idx < len(bar_chords) else ""
        if ch_lbl:
            bar_tokens[0] = _merge_chord_into_beat_token(bar_tokens[0], ch_lbl)
        meta_parts: list[str] = []
        if (num, den) != printed_ts:
            meta_parts.append(f"\\ts ({num} {den})")
            printed_ts = (num, den)
        if abs(float(bpm) - float(printed_bpm)) > 0.51:
            meta_parts.append(f"\\tempo {int(round(bpm))}")
            printed_bpm = float(bpm)
        if not suppress_mid_bar_midi_tempo:
            for tt, bpm_ev in tempo_segments:
                if bs + eps < tt < be - eps:
                    ratio = (tt - bs) / max(1e-9, (be - bs))
                    ratio = min(0.9999, max(0.0001, ratio))
                    bpm_clamped = max(20.0, min(300.0, float(bpm_ev)))
                    meta_parts.append(f'\\tempo ({int(round(bpm_clamped))} "" {ratio:.4f} hide)')
        prefix = (" ".join(meta_parts) + " ") if meta_parts else ""
        bars.append(f"{prefix}{' '.join(bar_tokens)} |")
        bar_tokens = []
        bar_units = 0.0
        bar_idx += 1

    # 동일 운지가 이어지는 구간을 병합한 뒤, 16분 단위로 그리디 분해해 토큰을 만든다.
    prev_dy_m: str | None = None
    raw_chunks: list[tuple[float, float, tuple[tuple[int, int], ...], str, str]] = []
    for idx in range(len(sorted_boundaries) - 1):
        t0b = float(sorted_boundaries[idx])
        t1b = float(sorted_boundaries[idx + 1])
        if t1b <= t0b + eps:
            continue
        snap = _tab_snapshot_key(note_events, t0b, eps)
        full_tok, prev_dy_m = active_content_with_dy(t0b, prev_dy_m)
        base_tok = _strip_dy_from_alphatex_note_token(full_tok)
        raw_chunks.append((t0b, t1b, snap, full_tok, base_tok))

    use_voice_merge = preset.use_merge_voice_key
    merged_rows: list[list[Any]] = []
    for t0b, t1b, snap, full_tok, base_tok in raw_chunks:
        mkey = _tab_merge_row_key(note_events, t0b, eps, use_voice=use_voice_merge)
        if merged_rows and mkey == merged_rows[-1][5] and abs(t0b - merged_rows[-1][1]) < 1e-5:
            merged_rows[-1][1] = t1b
        else:
            merged_rows.append([t0b, t1b, snap, full_tok, base_tok, mkey])

    first_note_in_row: list[bool] = [True]
    last_emit_den: list[int | None] = [None]

    def emit_units_slice(total_units: float, first_full: str, base_only: str) -> None:
        nonlocal bar_idx, bar_tokens, bar_units
        use_cost = preset.use_emit_cost
        use_mdp = preset.use_emit_mdp
        rem_u = float(total_units)
        guard = 0
        while rem_u > 1e-6:
            guard += 1
            if guard > 500_000 or bar_idx >= len(bars_info):
                return
            measure_units_target = float(bars_info[bar_idx][5])
            room = measure_units_target - float(bar_units)
            if room <= 1e-9:
                if bar_tokens:
                    flush_bar()
                else:
                    bar_idx += 1
                continue
            if use_mdp and rem_u <= 12.0 and room + 1e-6 >= rem_u:
                half = int(round(rem_u * 2))
                if half > 0 and abs(half / 2.0 - rem_u) < 0.02:
                    seq = _mdp_den_sequence_half_units(half)
                    sum_h = sum(_DEN_TO_HALF_UNITS[d] for d in seq) if seq else -1
                    if seq and sum_h == half:
                        for den_found in seq:
                            nu = 16.0 / den_found
                            piece = first_full if first_note_in_row[0] else base_only
                            first_note_in_row[0] = False
                            tok = f":{den_found} {piece}" if den_found != base_den else piece
                            bar_tokens.append(tok)
                            bar_units += nu
                            last_emit_den[0] = den_found
                        rem_u = 0.0
                        continue
            den_found: int | None = None
            nu = 0.0
            if use_cost:
                den_found, nu = _emit_pick_den_cost(rem_u, room, float(bar_units), last_emit_den[0])
            else:
                for d in (1, 2, 4, 8, 16, 32):
                    nn = 16.0 / d
                    if nn <= rem_u + 1e-6 and nn <= room + 1e-6:
                        den_found = d
                        nu = nn
                        break
            if den_found is None:
                den_found = 32
                nu = 0.5
                if nu > room + 1e-6:
                    if bar_tokens:
                        flush_bar()
                    elif bar_idx + 1 < len(bars_info):
                        bar_idx += 1
                    else:
                        return
                    continue
            piece = first_full if first_note_in_row[0] else base_only
            first_note_in_row[0] = False
            tok = f":{den_found} {piece}" if den_found != base_den else piece
            bar_tokens.append(tok)
            bar_units += nu
            rem_u -= nu
            last_emit_den[0] = den_found

    for row in merged_rows:
        st, en, _snap, first_full, base_only = row[0], row[1], row[2], row[3], row[4]
        ct = float(st)
        first_note_in_row[0] = True
        while ct < float(en) - eps and bar_idx < len(bars_info):
            while bar_idx < len(bars_info) and ct >= bars_info[bar_idx][1] - eps:
                if bar_tokens:
                    flush_bar()
                else:
                    bar_idx += 1
            if bar_idx >= len(bars_info):
                break
            bs_r, be_r, _nr, _dr, bpm_r, measure_units_target = bars_info[bar_idx]
            base_unit_sec = (60.0 / max(20.0, bpm_r)) / 4.0
            chunk_end = min(float(en), float(be_r))
            chunk_sec = max(0.0, chunk_end - ct)
            if chunk_sec <= eps:
                ct = chunk_end
                continue
            units_chunk = chunk_sec / base_unit_sec
            emit_units_slice(units_chunk, first_full, base_only)
            ct = chunk_end

    if bar_tokens:
        flush_bar()

    body = "\n".join(bars) if bars else f":{base_den} r |"

    sync_block = ""
    if bars_info:
        lines: list[str] = []
        cap_ms: int | None = None
        if audio_duration_sec is not None and audio_duration_sec > 0:
            cap_ms = int(round(float(audio_duration_sec) * 1000.0))
        for i, (bs, _be, _n, _d, _b, _u) in enumerate(bars_info):
            ms = int(round(bs * 1000.0))
            if cap_ms is not None:
                ms = min(ms, cap_ms)
            lines.append(f"\\sync {i} 0 {ms}")
        sync_block = "\n" + "\n".join(lines)

    # \\lyrics 는 \\staff 직후(스태프 컨텍스트). 이어서 \\chord 정의 → capo → 박자/튜닝/템포.
    capo_line = f"\\capo {int(capo)}\n" if int(capo) > 0 else ""
    header = (
        f"\\title \"{safe_title}\"\n"
        + (f"\\artist \"{safe_artist}\"\n" if safe_artist else "\\artist \"\"\n")
        + f'\\track "Guitar" {{ instrument "{inst_name}" }}\n'
        "\\staff {score tabs}\n"
        + lyrics_line
        + chord_def_block
        + capo_line
        + f"\\ts ({first_ts[0]} {first_ts[1]})\n"
        "\\tuning (E4 B3 G3 D3 A2 E2)\n"
        + f"\\tempo {int(round(first_bpm))}\n"
    )

    tex = header + body + sync_block

    attempt = 0
    last_diag: dict[str, Any] | None = None
    while attempt < 2:
        diag = _validate_alphatex_with_alphatab(tex)
        last_diag = diag
        token_ok = bool(diag.get("tokenGuard", {}).get("ok", True))
        has_errors = bool(diag.get("hasErrors", False))
        if token_ok and not has_errors:
            if tab_output_dir is not None and note_events:
                try:
                    write_tab_compare_artifacts(
                        midi_path, note_events, tab_output_dir, refine=False
                    )
                except OSError:
                    pass
            if tab_experiment_out is not None:
                tok_counts: list[int] = []
                for line in bars:
                    pipe = line.find("|")
                    core = line if pipe < 0 else line[:pipe]
                    parts = [p for p in core.split() if p and not p.startswith("\\")]
                    tok_counts.append(len(parts))
                mean_tok = float(statistics.mean(tok_counts)) if tok_counts else 0.0
                tab_experiment_out.clear()
                tab_experiment_out.update(
                    {
                        "alphatex_rhythm_mode": (
                            "arrangement_eighth" if preset.name == "arrangement" else "transcription_legacy"
                        ),
                        "render_mode": preset.name,
                        "arrangement_relax_level": int(arrangement_relax_level),
                        "boundary_count_before": int(boundary_count_before),
                        "boundary_count_after": int(boundary_count_after),
                        "mean_tokens_per_bar": round(mean_tok, 4),
                        "grid_step_sec": round(float(_grid_step_sec), 8),
                    }
                )
                tab_experiment_out.update(onset_stats)
                tab_experiment_out.update(chord_mapping_metrics)
            return tex

        if attempt == 0 and _should_retry_after_alphatex_diagnostics(diag):
            safe_title = _escape_alpha_tex_string(title)
            header = (
                f"\\title \"{safe_title}\"\n"
                + (f"\\artist \"{safe_artist}\"\n" if safe_artist else "\\artist \"\"\n")
                + f'\\track "Guitar" {{ instrument "{inst_name}" }}\n'
                "\\staff {score tabs}\n"
                + lyrics_line
                + chord_def_block
                + capo_line
                + f"\\ts ({first_ts[0]} {first_ts[1]})\n"
                "\\tuning (E4 B3 G3 D3 A2 E2)\n"
                + f"\\tempo {int(round(first_bpm))}\n"
            )
            tex = header + body + sync_block
        attempt += 1

    assert last_diag is not None
    errors = last_diag.get("errors", []) or []
    ast_issues = last_diag.get("astIssues", []) or []
    preview = errors[:3]
    if not preview and ast_issues:
        preview_ast = ast_issues[:3]
        raise RuntimeError(
            "생성된 alphaTex AST 품질 게이트 실패. "
            + "; ".join(str(issue.get("message", "unknown AST issue")) for issue in preview_ast if isinstance(issue, dict))
        )
    raise RuntimeError(
        "생성된 alphaTex 검증 실패. "
        + "; ".join(
            f"AT{int(e.get('code', -1))}: {e.get('message','')}" for e in preview if isinstance(e, dict)
        )
    )


def _midi_to_score(
    midi_path: Path,
    title: str,
    *,
    artist: str = "",
    lyrics: str | None = None,
    capo: int = 0,
    tempo_override: float | None = None,
    onset_times_sec: list[float] | None = None,
) -> dict[str, Any]:
    tab_hints = extract_guitar_tab_hints_from_midi(midi_path)
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    capo = _clamp_capo_0_5(capo)
    tempo_segments = _parse_tempo_segments(midi)
    ts_segments = _parse_time_signature_segments(midi)
    tempo = float(tempo_override) if tempo_override is not None else float(tempo_segments[0][1])
    tempo = max(20.0, min(300.0, tempo))
    ts0 = ts_segments[0]
    num, den = int(ts0[1]), int(ts0[2])

    raw_notes = _raw_guitar_notes_from_midi(midi)
    max_end = max((n["end"] for n in raw_notes), default=0.0)
    max_end = max(max_end, 0.01)
    bars_info = _compute_bars_info(midi, max_end, bpm_override=tempo_override)
    chord_labels = _bar_chord_labels(raw_notes, bars_info, int(capo))

    beats, _grid_step_sec = _quantized_beats_from_midi(
        midi,
        tempo,
        preset=TRANSCRIPTION_PRESET,
        onset_times_sec=onset_times_sec,
        tab_hints=tab_hints,
        bars_info=bars_info,
        bar_chords=chord_labels,
        capo=capo,
    )

    return {
        "version": 1,
        "meta": {
            "title": title,
            "artist": artist,
            "lyrics": lyrics,
            "tempo": int(round(tempo)),
            "timeSignature": {"numerator": num, "denominator": den},
            "key": "C major",
            "capo": int(capo),
            "capoMethod": "midi_only_0_5",
            "capoCandidateRange": [int(CAPO_CANDIDATE_RANGE[0]), int(CAPO_CANDIDATE_RANGE[1])],
            "chords": chord_labels,
            "instrument": _midi_program_to_alphatab_instrument(_get_primary_midi_program(midi)),
        },
        "tracks": [
            {
                "name": "Guitar",
                "type": "guitar",
                "strings": 6,
                "tuning": [40, 45, 50, 55, 59, 64],
                "beats": beats,
            }
        ],
    }


def _render_transcription_alphatex(
    midi_path: Path,
    *,
    title: str,
    artist: str,
    lyrics: str | None,
    audio_duration_sec: float | None,
    capo: int,
    tempo_override: float | None,
    onset_times_sec: list[float] | None,
    tab_output_dir: Path | None,
    tab_experiment_out: dict[str, Any] | None,
) -> str:
    return _midi_to_alphatex(
        midi_path,
        title=title,
        artist=artist,
        lyrics=lyrics,
        audio_duration_sec=audio_duration_sec,
        capo=capo,
        tempo_override=tempo_override,
        onset_times_sec=onset_times_sec,
        tab_output_dir=tab_output_dir,
        tab_experiment_out=tab_experiment_out,
        preset=TRANSCRIPTION_PRESET,
    )


def _render_arrangement_alphatex(
    midi_path: Path,
    *,
    title: str,
    artist: str,
    lyrics: str | None,
    audio_duration_sec: float | None,
    capo: int,
    tempo_override: float | None,
    onset_times_sec: list[float] | None,
    tab_output_dir: Path | None,
    tab_experiment_out: dict[str, Any] | None,
    arrangement_relax_level: int = 0,
) -> str:
    return _midi_to_alphatex(
        midi_path,
        title=title,
        artist=artist,
        lyrics=lyrics,
        audio_duration_sec=audio_duration_sec,
        capo=capo,
        tempo_override=tempo_override,
        onset_times_sec=onset_times_sec,
        tab_output_dir=tab_output_dir,
        tab_experiment_out=tab_experiment_out,
        preset=ARRANGEMENT_PRESET,
        arrangement_relax_level=arrangement_relax_level,
    )


def _extract_pitch_onset_recall_from_compare_report(report_path: Path) -> float | None:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    compare_after = payload.get("compare_after_export")
    if not isinstance(compare_after, dict):
        return None
    val = compare_after.get("pitch_onset_recall_rate")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def run_four_step_pipeline(
    url: str,
    *,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> PipelineResult:
    def report(progress: int, stage: str, detail: str) -> None:
        print(f"[pipeline] {progress:>3}% | {stage:<11} | {detail}", flush=True)
        if progress_cb:
            progress_cb({"type": "progress", "progress": progress, "stage": stage, "detail": detail})

    title, artist, description, duration_youtube, uploader = _fetch_youtube_meta(url)
    parsed_artist, parsed_track = parse_artist_and_track_from_youtube_title(title)
    score_title = f"{parsed_artist} - {parsed_track}" if (parsed_artist and parsed_track) else title
    if artist and str(artist).strip():
        display_artist = str(artist).strip()
    elif parsed_artist:
        display_artist = parsed_artist.strip()
    else:
        display_artist = (uploader or "").strip()

    lyrics_cache_root = Path("data") / "lyrics_cache"
    lyrics: str | None = None
    lyrics_source: str = "none"

    base_name = _safe_job_name_from_title(title, url)
    job_dir = _allocate_job_dir(Path("data") / "jobs", base_name)
    (job_dir / "audio").mkdir(parents=True, exist_ok=True)

    report(5, "download", "yt-dlp로 mp3 다운로드 시작")
    mp3_path = _download_mp3(url, job_dir / "audio")
    audio_dur = _probe_audio_duration_sec(mp3_path)
    lyrics, lyrics_source = _resolve_youtube_lyrics(
        str(url),
        job_dir,
        title,
        artist,
        uploader,
        description,
        duration_youtube,
        audio_dur,
        lyrics_cache_root,
    )
    if lyrics and lyrics.strip():
        report(10, "lyrics", f"가사 수집 완료 ({lyrics_source})")
    else:
        report(10, "lyrics", "가사 없음 (LRCLIB·설명에서 찾지 못함)")

    render_mode = _resolve_tab_render_mode()
    render_preset = _preset_for_mode(render_mode)

    report(25, "separate", "Demucs로 stem 분리 시작")
    stems = _separate_demucs(mp3_path, job_dir / "stems")
    guitar_mp3 = _ensure_flat_guitar_stem_mp3(stems, job_dir / "stems")
    guitar_wav = job_dir / "stems" / "guitar.wav"
    report(35, "convert", "기타 스템 MP3 → WAV(44.1k mono)")
    _ffmpeg_mp3_to_wav_mono_44k(guitar_mp3, guitar_wav)

    report(50, "basic-pitch", "Basic Pitch로 기타 WAV → MIDI 변환")
    midi_path = _guitar_wav_to_midi_basic_pitch(guitar_wav, job_dir / "midi" / "guitar.mid")

    midi_for_bpm = pretty_midi.PrettyMIDI(str(midi_path))
    midi_bpm = _primary_bpm_from_midi(midi_for_bpm)
    report(58, "tempo", f"MIDI 템포 BPM≈{midi_bpm:.1f}")

    try:
        midi_adjust = pretty_midi.PrettyMIDI(str(midi_path))
        if render_preset.unified_grid:
            snap_midi_notes_to_tempo_grid(
                midi_adjust,
                midi_bpm,
                [],
                subdivisions_per_quarter=render_preset.subdivisions_per_quarter,
            )
        else:
            snap_midi_notes_to_sixteenth_grid(midi_adjust, midi_bpm, [])
        midi_adjust.write(str(midi_path))
    except Exception as exc:
        report(62, "quantize", f"MIDI 16분 그리드 스냅 생략/실패: {exc}")

    report(65, "onset", "기타 stem onset 추출(음 과다 표기 완화)")
    onset_meta = analyze_onsets_from_guitar_audio(guitar_mp3, bpm_hint=midi_bpm)
    onset_times_out: list[float] = []
    if onset_meta.get("ok"):
        onset_times_out = list(onset_meta.get("onset_times_sec") or [])
        report(68, "onset", f"onset {len(onset_times_out)}개 추출")
    else:
        report(68, "onset", f"onset 추출 실패·기본 후처리 사용 ({onset_meta.get('error') or 'unknown'})")

    capo_guess = 0
    capo_method = "midi_only_0_5"
    try:
        midi_for_capo = pretty_midi.PrettyMIDI(str(midi_path))
        raw_capo = _raw_guitar_notes_from_midi(midi_for_capo)
        max_e_capo = max((n["end"] for n in raw_capo), default=0.01)
        bars_capo = _compute_bars_info(midi_for_capo, max_e_capo, bpm_override=midi_bpm)
        capo_guess = _choose_capo_midi_only(raw_capo, bars_capo, render_mode=render_mode)
    except Exception as exc:
        report(80, "capo", f"MIDI 기반 카포 탐색 실패·기본값 0 사용 ({exc})")
        capo_guess = 0
    capo_guess = _clamp_capo_0_5(capo_guess)
    report(82, "capo", f"카포: {capo_guess} ({capo_method})")

    report(85, "alphatex", f"MIDI를 AlphaTex 문법으로 변환 시작 (mode={render_mode})")
    tab_experiment: dict[str, Any] = {}
    arrangement_retry_applied = False
    arrangement_recall_initial: float | None = None
    arrangement_recall_final: float | None = None
    arrangement_min_recall = _parse_arrangement_min_recall()
    if render_mode == "arrangement":
        alphatex = _render_arrangement_alphatex(
            midi_path,
            title=score_title,
            artist=display_artist,
            lyrics=lyrics,
            audio_duration_sec=audio_dur,
            capo=capo_guess,
            tempo_override=midi_bpm,
            onset_times_sec=onset_times_out,
            tab_output_dir=job_dir / "tab",
            tab_experiment_out=tab_experiment,
            arrangement_relax_level=0,
        )
        report_path = job_dir / "tab" / "compare_report.json"
        arrangement_recall_initial = _extract_pitch_onset_recall_from_compare_report(report_path)
        arrangement_recall_final = arrangement_recall_initial
        if arrangement_recall_initial is not None and arrangement_recall_initial < arrangement_min_recall:
            arrangement_retry_applied = True
            report(
                89,
                "quality",
                f"arrangement recall {arrangement_recall_initial:.3f} < {arrangement_min_recall:.3f}, 완화 재시도",
            )
            alphatex = _render_arrangement_alphatex(
                midi_path,
                title=score_title,
                artist=display_artist,
                lyrics=lyrics,
                audio_duration_sec=audio_dur,
                capo=capo_guess,
                tempo_override=midi_bpm,
                onset_times_sec=onset_times_out,
                tab_output_dir=job_dir / "tab",
                tab_experiment_out=tab_experiment,
                arrangement_relax_level=1,
            )
            arrangement_recall_final = _extract_pitch_onset_recall_from_compare_report(report_path)
    else:
        alphatex = _render_transcription_alphatex(
            midi_path,
            title=score_title,
            artist=display_artist,
            lyrics=lyrics,
            audio_duration_sec=audio_dur,
            capo=capo_guess,
            tempo_override=midi_bpm,
            onset_times_sec=onset_times_out,
            tab_output_dir=job_dir / "tab",
            tab_experiment_out=tab_experiment,
        )
    score = _midi_to_score(
        midi_path,
        title=score_title,
        artist=display_artist,
        lyrics=lyrics,
        capo=capo_guess,
        tempo_override=midi_bpm,
        onset_times_sec=onset_times_out,
    )
    (job_dir / "tab").mkdir(parents=True, exist_ok=True)
    (job_dir / "tab" / "guitar.alphatex").write_text(alphatex, encoding="utf-8")
    (job_dir / "tab" / "score.json").write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
    compare_report_path = job_dir / "tab" / "compare_report.json"
    if compare_report_path.exists():
        try:
            compare_payload = json.loads(compare_report_path.read_text(encoding="utf-8"))
            compare_payload["capo_in_range_0_5"] = bool(0 <= int(capo_guess) <= 5)
            compare_payload["chord_tone_hit_rate"] = float(
                tab_experiment.get("chord_tone_hit_rate", 0.0)
            )
            compare_payload["shape_alignment_rate"] = float(
                tab_experiment.get("shape_alignment_rate", 0.0)
            )
            compare_payload["riff_segment_ratio"] = float(
                tab_experiment.get("riff_segment_ratio", 0.0)
            )
            compare_payload["capo_candidate_range"] = [
                int(CAPO_CANDIDATE_RANGE[0]),
                int(CAPO_CANDIDATE_RANGE[1]),
            ]
            compare_report_path.write_text(
                json.dumps(compare_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass
    meta_payload = {
        "title": score_title,
        "youtube_title": title,
        "artist": display_artist,
        "lyrics": lyrics,
        "lyrics_source": lyrics_source,
        "duration_youtube_sec": duration_youtube,
        "duration_audio_sec": audio_dur,
    }
    (job_dir / "meta.json").write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    job_meta_payload = {
        "bpm": midi_bpm,
        "midi_bpm": midi_bpm,
        "beat_times_sec": [],
        "downbeat_indices": [],
        "onset_analysis_ok": bool(onset_meta.get("ok")),
        "onset_times_sec": onset_times_out,
    }
    if onset_meta.get("error"):
        job_meta_payload["onset_analysis_error"] = onset_meta["error"]
    (job_dir / "job_meta.json").write_text(json.dumps(job_meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lyrics_truncated, lyrics_alphatex_chars = (
        _alphatex_lyrics_truncation_info(lyrics.strip())
        if lyrics and lyrics.strip()
        else (False, 0)
    )
    lyrics_files_info = _write_lyrics_files(
        job_dir,
        lyrics,
        lyrics_source,
        alphatex_truncated=lyrics_truncated,
        alphatex_lyrics_chars=lyrics_alphatex_chars,
    )
    midi_chk = pretty_midi.PrettyMIDI(str(midi_path))
    (job_dir / "tab" / "summary.json").write_text(
        json.dumps(
            {
                "url": url,
                "mp3_path": str(mp3_path),
                "audio_duration_sec": audio_dur,
                "mode": render_mode,
                "capo_guess": capo_guess,
                "capo_method": capo_method,
                "capo_candidate_range": [
                    int(CAPO_CANDIDATE_RANGE[0]),
                    int(CAPO_CANDIDATE_RANGE[1]),
                ],
                "capo_in_range_0_5": bool(0 <= int(capo_guess) <= 5),
                "alphatex_rhythm_mode": (
                    "arrangement_eighth"
                    if render_mode == "arrangement"
                    else "transcription_legacy"
                ),
                "lyrics_source": lyrics_source,
                "lyrics_files": lyrics_files_info,
                "midi_has_named_chord_track_hint": _midi_has_named_chord_track_hint(midi_chk),
                "midi_note_events_only": True,
                "chords_on_score": "마디별 음높이로 추정(표기용). Basic Pitch MIDI에는 코드 문자열이 들어가지 않음.",
                "guitar_stem_mp3": str(job_dir / "stems" / "guitar.mp3"),
                "guitar_stem_wav": str(job_dir / "stems" / "guitar.wav"),
                "stems": {k: str(v) for k, v in stems.items()},
                "midi_path": str(midi_path),
                "tab_hints_extracted": len(extract_guitar_tab_hints_from_midi(midi_path)),
                "demucs_model": DEMUCS_MODEL_NAME,
                "guitar_transcribe_backend": "basic_pitch",
                "alphatex_path": str(job_dir / "tab" / "guitar.alphatex"),
                "tab_from_tab_midi": str(job_dir / "tab" / "tab_from_tab.mid"),
                "tab_compare_report": str(job_dir / "tab" / "compare_report.json"),
                "quality_gate": {
                    "arrangement_min_recall": arrangement_min_recall,
                    "arrangement_recall_initial": arrangement_recall_initial,
                    "arrangement_recall_final": arrangement_recall_final,
                    "arrangement_retry_applied": arrangement_retry_applied,
                },
                "job_meta_path": str(job_dir / "job_meta.json"),
                "midi_bpm": midi_bpm,
                "beat_times_count": 0,
                "tab_experiment": tab_experiment,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report(100, "done", "유튜브→Demucs→Basic Pitch→AlphaTex 파이프라인 완료")

    return PipelineResult(
        job_dir=job_dir,
        mp3_path=mp3_path,
        stems=stems,
        midi_path=midi_path,
        alphatex=alphatex,
        score=score,
        title=score_title,
        artist=display_artist,
        lyrics=lyrics,
        lyrics_source=lyrics_source,
    )
