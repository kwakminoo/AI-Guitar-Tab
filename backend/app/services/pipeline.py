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
import tempfile
import uuid
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pretty_midi
import numpy as np

from .lyrics_lrclib import fetch_lyrics_from_lrclib, parse_artist_and_track_from_youtube_title
from .tab_playback import refine_note_events_with_reference_midi, write_tab_compare_artifacts

GUITAR_OPEN_MIDI = [64, 59, 55, 50, 45, 40]  # E4, B3, G3, D3, A2, E2
GUITAR_MIN_PITCH = 40
GUITAR_MAX_PITCH = 88
MIN_NOTE_VELOCITY = 18
ONSET_TOLERANCE_SEC = 0.035
MERGE_MIN_IOI_SEC = 0.100
SUSTAIN_RELEASE_SEC = 0.050
MAX_SUSTAIN_BEATS = 1.5
MAX_NOTES_PER_SLOT = 2
CHORD_EXTRA_PENALTY = 0.30
CHORD_MIN_SCORE_RATIO = 0.10
CHORD_BASS_PRIOR_SCALE = 0.35
CHORD_KEY_CONTEXT_BONUS = 0.12
CHORD_NGRAM_ROOT_JUMP_PENALTY = 0.22
CHORD_NGRAM_QUALITY_SWITCH_PENALTY = 0.16
CHORD_SHORT_NOTE_RATIO = 0.20
CHORD_SHORT_NOTE_WEIGHT = 0.40
MIDI_CLEANUP_ENABLED = True
MIDI_CLEANUP_MIN_DURATION_SEC = 0.08
MIDI_CLEANUP_DUPLICATE_START_TOLERANCE_SEC = 0.07
MIDI_CLEANUP_VELOCITY_FLOOR = 20
MIDI_CLEANUP_VELOCITY_RELATIVE_RATIO = 0.40
MIDI_SNAP_ENABLED = False
MIDI_SNAP_MAX_ERROR_SEC = 0.03
MIDI_SNAP_NOTE_END = False
DURATION_32_RATIO_TARGET_PCT = 35.0
BAR_32_RATIO_LIMIT_PCT = 35.0
BAR_ATTACK_MAX_COUNT = 10
CHORD_FIRST_SIMPLIFY = False

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


# AlphaTex // 단일 줄 주석(렉서가 무시). 마디 줄 직전에 삽입.
INTERLEAVED_LYRIC_MIN_GAP_SEC = 0.55
INTERLEAVED_LYRIC_MAX_LINES_PER_BAR = 2


def _sanitize_alphatex_single_line_comment(text: str) -> str:
    """AlphaTex // 주석 본문(한 줄). 줄바꿈·제어 문자 제거, /* */ 시퀀스는 깨짐 방지용으로 완화."""
    s = (text or "").replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    s = s.replace("/*", " / ").replace("*/", " / ")
    return s


def _remove_lyrics_metadata_line(tex: str) -> str:
    """헤더의 \\lyrics 메타 제거(인터리브 모드에서 이중 표기 방지)."""
    out: list[str] = []
    for line in tex.split("\n"):
        if re.match(r'^\s*\\lyrics(?:\s+\d+)?\s+"(?:\\.|[^"\\])*"\s*$', line):
            continue
        out.append(line)
    return "\n".join(out)


def _build_staff_lyrics_commands(
    aligned_timed_lyrics: list[dict[str, Any]],
    bars_info: list[tuple[float, float, int, int, float, int]],
    *,
    max_lines: int = 48,
) -> list[str]:
    """timed 가사를 시작 마디 기반 \\lyrics N \"...\" 라인들로 변환한다."""
    if not aligned_timed_lyrics or not bars_info:
        return []
    grouped: dict[int, list[str]] = defaultdict(list)
    for it in aligned_timed_lyrics:
        raw = str(it.get("line") or it.get("text", "")).strip()
        if not raw:
            continue
        try:
            t0 = float(it.get("start_sec", 0.0))
        except (TypeError, ValueError):
            t0 = 0.0
        bi = _bar_index_for_time_sec(t0, bars_info)
        bi = min(max(0, bi), len(bars_info) - 1)
        txt = _sanitize_alphatex_single_line_comment(raw)
        if txt:
            grouped[bi].append(txt)

    if not grouped:
        return []

    out: list[str] = []
    for bi in sorted(grouped.keys()):
        merged = " ".join(grouped[bi]).strip()
        if not merged:
            continue
        # alphaTex startBar는 1-indexed.
        start_bar = int(bi) + 1
        out.append(f'\\lyrics {start_bar} "{_escape_alpha_tex_lyrics(merged)}"')
        if len(out) >= max(1, int(max_lines)):
            break
    return out


def _inject_lyrics_after_staff_line(head: str, lyric_commands: list[str]) -> str:
    """\\staff 줄 직후에 \\lyrics 라인 블록을 넣어 alphaTab 뷰어에 가사가 그려지게 한다."""
    cmds = [c for c in lyric_commands if str(c).strip()]
    if not cmds:
        return head
    if re.search(r"(?m)^\s*\\lyrics(?:\s+\d+)?\s+\"", head):
        return head
    lines = head.split("\n")
    out: list[str] = []
    inserted = False
    for ln in lines:
        out.append(ln)
        if not inserted and re.match(r"^\s*\\staff\s+", ln.strip()):
            out.extend(cmds)
            inserted = True
    if not inserted:
        return "\n".join(cmds) + "\n" + head
    return "\n".join(out)


def _split_alphatex_at_first_sync(tex: str) -> tuple[str, str] | None:
    m = re.search(r"(?m)^\\sync\s+\d+\s+", tex)
    if not m:
        return None
    return tex[: m.start()], tex[m.start() :]


def _bar_index_for_time_sec(
    t: float,
    bars_info: list[tuple[float, float, int, int, float, int]],
) -> int:
    eps = 1e-6
    t = max(0.0, float(t))
    if not bars_info:
        return 0
    for i, row in enumerate(bars_info):
        bs, be = float(row[0]), float(row[1])
        if bs - eps <= t < be - eps:
            return i
    starts = [float(row[0]) for row in bars_info]
    return min(range(len(starts)), key=lambda j: abs(starts[j] - t))


def _first_bar_line_index(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        s = line.strip()
        if s.endswith("|"):
            return i
    return None


def _build_interleaved_comment_lines_per_bar(
    aligned_timed_lyrics: list[dict[str, Any]],
    bars_info: list[tuple[float, float, int, int, float, int]],
    bar_line_count: int,
    *,
    max_chars_total: int,
) -> list[list[str]]:
    """각 마디(출력 줄)당 0~2줄의 주석 본문(// 접두 없음)."""
    if bar_line_count < 1:
        return []
    items: list[tuple[float, str]] = []
    for it in aligned_timed_lyrics:
        raw = str(it.get("line") or it.get("text", "")).strip()
        if not raw:
            continue
        st = _sanitize_alphatex_single_line_comment(raw)
        if not st:
            continue
        try:
            t0 = float(it.get("start_sec", 0.0))
        except (TypeError, ValueError):
            t0 = 0.0
        items.append((t0, st))
    items.sort(key=lambda x: x[0])

    by_bar: dict[int, list[tuple[float, str]]] = defaultdict(list)
    last_bi = bar_line_count - 1
    for t0, st in items:
        bi = _bar_index_for_time_sec(t0, bars_info)
        bi = min(max(bi, 0), last_bi)
        by_bar[bi].append((t0, st))

    per_bar: list[list[str]] = [[] for _ in range(bar_line_count)]

    for bi in sorted(by_bar.keys()):
        seq = sorted(by_bar[bi], key=lambda x: x[0])
        if not seq:
            continue
        if len(seq) == 1:
            per_bar[bi] = [seq[0][1]]
            continue
        t0, s0 = seq[0]
        t1, s1 = seq[1]
        if len(seq) == 2 and (t1 - t0) >= INTERLEAVED_LYRIC_MIN_GAP_SEC:
            per_bar[bi] = [s0, s1][:INTERLEAVED_LYRIC_MAX_LINES_PER_BAR]
        elif len(seq) == 2:
            per_bar[bi] = [f"{s0} · {s1}"]
        else:
            merged = " · ".join(x[1] for x in seq)
            per_bar[bi] = [merged][:INTERLEAVED_LYRIC_MAX_LINES_PER_BAR]

    # 문자 예산: 마디 순서대로 줄 단위로 채우다가 초과 시 마지막 줄만 잘라냄
    out: list[list[str]] = [[] for _ in range(bar_line_count)]
    used = 0
    for bi in range(bar_line_count):
        for line in per_bar[bi]:
            if used >= max_chars_total:
                break
            room = max_chars_total - used
            if len(line) <= room:
                out[bi].append(line)
                used += len(line)
            else:
                if room > 0:
                    out[bi].append(line[:room])
                    used = max_chars_total
                break
        if used >= max_chars_total:
            break
    return out


def _apply_interleaved_lyrics_to_alphatex(
    tex: str,
    midi_path: Path,
    bpm_override: float | None,
    aligned_timed_lyrics: list[dict[str, Any]],
    plain_lyrics_for_staff: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    timed 가사를 // 주석으로 마디 줄 직전에 삽입한다.
    기존 헤더 \\lyrics 는 한 번 제거한 뒤, plain_lyrics_for_staff 가 있으면 \\staff 직후에 다시 넣어
    alphaTab 악보에 가사(음절·박 매핑)가 그려지게 한다.
    실패 시 원본 tex 반환.
    """
    meta: dict[str, Any] = {
        "applied": False,
        "layout": "header_lyrics",
        "error": None,
        "skipped_reason": None,
        "validator_ok_after": None,
        "bar_line_count": 0,
        "interleaved_char_count": 0,
        "staff_lyrics_reinjected": False,
    }
    if not aligned_timed_lyrics or not any(
        str(it.get("line") or it.get("text", "")).strip() for it in aligned_timed_lyrics
    ):
        meta["layout"] = "none"
        meta["skipped_reason"] = "no_timed_text"
        return tex, meta

    split = _split_alphatex_at_first_sync(tex)
    if split is None:
        meta["skipped_reason"] = "no_sync_block"
        return tex, meta

    head, sync_part = split
    head_lines = head.split("\n")
    first_bar_i = _first_bar_line_index(head_lines)
    if first_bar_i is None:
        meta["skipped_reason"] = "no_bar_lines"
        return tex, meta

    prefix_lines = head_lines[:first_bar_i]
    bar_lines = head_lines[first_bar_i:]
    bar_line_count = len(bar_lines)
    if bar_line_count < 1:
        meta["skipped_reason"] = "empty_bars"
        return tex, meta

    try:
        midi = pretty_midi.PrettyMIDI(str(midi_path))
        raw_notes = _raw_guitar_notes_from_midi(midi)
        max_end = max((n["end"] for n in raw_notes), default=0.0)
        max_end = max(float(max_end), 0.01)
        bars_info = _compute_bars_info(midi, max_end, bpm_override=bpm_override)
    except Exception as exc:
        meta["skipped_reason"] = f"bars_info:{exc}"
        return tex, meta

    if len(bars_info) < 1:
        meta["skipped_reason"] = "empty_bars_info"
        return tex, meta

    per_bar_comments = _build_interleaved_comment_lines_per_bar(
        aligned_timed_lyrics,
        bars_info,
        bar_line_count,
        max_chars_total=LYRICS_ALPHA_TEX_MAX_CHARS,
    )
    interleaved_chars = sum(len(s) for row in per_bar_comments for s in row)
    meta["interleaved_char_count"] = int(interleaved_chars)
    if interleaved_chars < 1:
        meta["skipped_reason"] = "no_comment_after_map"
        return tex, meta

    new_bar_parts: list[str] = []
    for j, bl in enumerate(bar_lines):
        cmt_lines = per_bar_comments[j] if j < len(per_bar_comments) else []
        if cmt_lines:
            cmt_block = "\n".join(f"// {c}" for c in cmt_lines)
            new_bar_parts.append(f"{cmt_block}\n{bl}")
        else:
            new_bar_parts.append(bl)

    head_no_lyrics = _remove_lyrics_metadata_line("\n".join(prefix_lines))
    lyric_commands = _build_staff_lyrics_commands(aligned_timed_lyrics, bars_info)
    if not lyric_commands and plain_lyrics_for_staff and str(plain_lyrics_for_staff).strip():
        lyric_commands = [f'\\lyrics "{_escape_alpha_tex_lyrics(str(plain_lyrics_for_staff).strip())}"']
    if lyric_commands:
        head_no_lyrics = _inject_lyrics_after_staff_line(head_no_lyrics, lyric_commands)
        meta["staff_lyrics_reinjected"] = True
    new_head = head_no_lyrics.rstrip() + "\n" + "\n".join(new_bar_parts)
    new_tex = new_head + sync_part

    diag = _validate_alphatex_with_alphatab(new_tex)
    token_ok = bool(diag.get("tokenGuard", {}).get("ok", True))
    has_errors = bool(diag.get("hasErrors", False))
    meta["validator_ok_after"] = bool(token_ok and not has_errors)
    if not token_ok or has_errors:
        meta["error"] = "validator_failed_after_interleave"
        meta["fallback"] = "kept_original_with_header_lyrics"
        meta["staff_lyrics_reinjected"] = False
        return tex, meta

    meta["applied"] = True
    meta["layout"] = "interleaved_comment"
    meta["bar_line_count"] = int(bar_line_count)
    return new_tex, meta


def _write_lyrics_files(
    job_dir: Path,
    lyrics: str | None,
    lyrics_source: str,
    *,
    alphatex_truncated: bool,
    alphatex_lyrics_chars: int,
    lyrics_layout: str | None = None,
    alphatex_note_override: str | None = None,
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
    default_note = (
        "guitar.alphatex 헤더의 \\\\lyrics 에 동일 가사가 들어가며, "
        "alphaTab이 박마다 음절을 배치한다. "
        "문법: https://alphatab.net/docs/alphatex/metadata/staff/lyrics"
    )
    interleaved_note = (
        "guitar.alphatex: 각 마디 위 // 주석(편집 참고)과 함께 "
        "헤더 \\\\staff 직후 \\\\lyrics <startBar> \"...\" 가 들어가면 alphaTab 뷰어에 가사가 시작 마디 기준으로 그려진다. "
        "// 줄은 렌더에 보이지 않을 수 있다."
    )
    note = alphatex_note_override or (
        interleaved_note if lyrics_layout == "interleaved_comment" else default_note
    )
    tab_meta.write_text(
        json.dumps(
            {
                "source": lyrics_source,
                "char_count": len(text),
                "encoding": "utf-8",
                "alphatex_lyrics_chars": alphatex_lyrics_chars,
                "alphatex_lyrics_truncated": alphatex_truncated,
                "lyrics_layout": lyrics_layout,
                "files": {
                    "plain_root": str(root_txt.as_posix()),
                    "plain_next_to_alphatex": str(tab_txt.as_posix()),
                },
                "alphatex_note": note,
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


def _parse_timecode_to_sec(value: str) -> float | None:
    s = (value or "").strip().replace(",", ".")
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            sec = float(parts[2])
            return float(h * 3600 + m * 60 + sec)
        if len(parts) == 2:
            m = int(parts[0])
            sec = float(parts[1])
            return float(m * 60 + sec)
        return float(s)
    except ValueError:
        return None


def _parse_vtt_timed_lyrics(vtt_text: str, source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    lines = (vtt_text or "").replace("\r\n", "\n").split("\n")
    i = 0
    prev_text = ""
    while i < len(lines):
        s = lines[i].strip()
        i += 1
        if not s or s.upper().startswith("WEBVTT") or s.startswith("NOTE"):
            continue
        if "-->" not in s:
            continue
        parts = s.split("-->")
        if len(parts) != 2:
            continue
        st = _parse_timecode_to_sec(parts[0].strip())
        en = _parse_timecode_to_sec(parts[1].strip().split(" ")[0])
        if st is None:
            continue
        payload: list[str] = []
        while i < len(lines):
            t = lines[i].strip()
            if not t:
                i += 1
                break
            if "-->" in t:
                break
            t = re.sub(r"<[^>]+>", "", t).strip()
            if t and not re.match(r"^(kind|language)\s*:", t, flags=re.I):
                payload.append(t)
            i += 1
        text = " ".join(payload).strip()
        if not text or text == prev_text:
            continue
        out.append(
            {
                "line": text,
                "start_sec": round(float(st), 3),
                "end_sec": round(float(en if en is not None else st + 2.0), 3),
                "source": source,
            }
        )
        prev_text = text
    return out


def _parse_lrc_timed_lyrics(lrc_text: str, source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    prev_text = ""
    for raw in (lrc_text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        tags = re.findall(r"\[(\d{1,2}:\d{1,2}(?:[.:]\d{1,3})?)\]", line)
        if not tags:
            continue
        text = re.sub(r"\[[^\]]+\]", "", line).strip()
        if not text or text == prev_text:
            continue
        for tg in tags:
            st = _parse_timecode_to_sec(tg)
            if st is None:
                continue
            out.append(
                {
                    "line": text,
                    "start_sec": round(float(st), 3),
                    "end_sec": None,
                    "source": source,
                }
            )
        prev_text = text
    out = sorted(out, key=lambda x: float(x.get("start_sec", 0.0)))
    for idx in range(len(out)):
        st = float(out[idx]["start_sec"])
        nxt = float(out[idx + 1]["start_sec"]) if idx + 1 < len(out) else st + 2.0
        out[idx]["end_sec"] = round(max(st + 0.1, nxt), 3)
    return out


def _timed_lyrics_to_plain(timed: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    prev = ""
    for item in timed:
        text = str(item.get("line", "")).strip()
        if not text or text == prev:
            continue
        lines.append(text)
        prev = text
    return "\n".join(lines).strip()


def _lyrics_char_ratio(text: str) -> float:
    s = (text or "").strip()
    if not s:
        return 0.0
    allowed = re.findall(r"[A-Za-z0-9가-힣ぁ-んァ-ヶ一-龯]", s)
    return float(len(allowed)) / float(max(1, len(s)))


def _is_noise_lyric_line(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    lowered = s.lower()
    if re.search(r"(번역|자막|subtitle|captions|credit|trans by|\bsub\b)", lowered, flags=re.I):
        return True
    if len(s) <= 2:
        return True
    if _lyrics_char_ratio(s) < 0.35:
        return True
    return False


def _filter_timed_lyrics_noise(
    timed: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    removed = 0
    prev = ""
    for item in timed:
        text = str(item.get("line", "")).strip()
        if not text or _is_noise_lyric_line(text):
            removed += 1
            continue
        if text == prev:
            removed += 1
            continue
        kept.append(item)
        prev = text
    return kept, {
        "before_line_count": int(len(timed)),
        "after_line_count": int(len(kept)),
        "removed_line_count": int(removed),
    }


def _read_url_json(url: str, *, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "ai-guitar-tab/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8", errors="replace"))


def _fetch_lrclib_timed_lyrics(
    title: str,
    artist: str | None,
    uploader: str | None,
    duration_sec: float | None,
) -> tuple[list[dict[str, Any]], str]:
    parsed_artist, parsed_track = parse_artist_and_track_from_youtube_title(title)
    artist_q = (artist or parsed_artist or uploader or "").strip()
    track_q = (parsed_track or title or "").strip()
    if not artist_q or not track_q:
        return [], "none"
    params = urllib.parse.urlencode({"track_name": track_q, "artist_name": artist_q})
    try:
        data = _read_url_json(f"https://lrclib.net/api/search?{params}")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return [], "none"
    if not isinstance(data, list):
        return [], "none"
    best: dict[str, Any] | None = None
    best_score = -1e9
    for item in data:
        if not isinstance(item, dict):
            continue
        synced = str(item.get("syncedLyrics") or "").strip()
        if not synced:
            continue
        score = 0.0
        dur = item.get("duration")
        if duration_sec is not None and dur is not None:
            try:
                score -= abs(float(duration_sec) - float(dur))
            except (TypeError, ValueError):
                pass
        if score > best_score:
            best_score = score
            best = item
    if best is None:
        return [], "none"
    timed = _parse_lrc_timed_lyrics(str(best.get("syncedLyrics") or ""), "lrclib_synced")
    return timed, ("lrclib_synced" if timed else "none")


def _align_timed_lyrics_to_timeline(
    timed: list[dict[str, Any]],
    beat_anchors_sec: list[float],
    *,
    use_piecewise: bool = True,
) -> tuple[list[dict[str, Any]], float, float, str, list[dict[str, Any]]]:
    if not timed:
        return [], 0.0, 0.0, "global", []
    anchors = sorted(set(float(t) for t in beat_anchors_sec if float(t) >= 0.0))
    if not anchors:
        return timed, 0.0, 0.0, "global", []

    def nearest_gap(anchor_list: list[float], v: float) -> float:
        pos = bisect.bisect_left(anchor_list, v)
        cands: list[float] = []
        if pos < len(anchor_list):
            cands.append(abs(anchor_list[pos] - v))
        if pos > 0:
            cands.append(abs(anchor_list[pos - 1] - v))
        return min(cands) if cands else 999.0

    def score_for_offset(items: list[dict[str, Any]], off: float) -> float:
        if not items:
            return -1e9
        gaps = [nearest_gap(anchors, float(it.get("start_sec", 0.0)) + off) for it in items]
        close = sum(1 for g in gaps if g <= 0.12)
        return close - (sum(gaps) / max(1, len(gaps)))

    def find_best_offset(items: list[dict[str, Any]]) -> tuple[float, float]:
        best_offset_local = 0.0
        best_score_local = -1e9
        for k in range(-30, 31):
            off = k * 0.05
            score = score_for_offset(items, off)
            if score > best_score_local:
                best_score_local = score
                best_offset_local = off
        return best_offset_local, best_score_local

    best_offset, best_score = find_best_offset(timed)

    aligned: list[dict[str, Any]] = []
    closeness: list[float] = []
    mode = "global"
    segments: list[dict[str, Any]] = []

    def apply_items(items: list[dict[str, Any]], off: float, seg_start: float, seg_end: float, seg_score: float) -> None:
        for item in items:
            st = max(0.0, float(item.get("start_sec", 0.0)) + off)
            en = max(st + 0.1, float(item.get("end_sec", st + 1.5)) + off)
            gap = nearest_gap(anchors, st)
            closeness.append(max(0.0, 1.0 - min(1.0, gap / 0.25)))
            mapped = dict(item)
            mapped["start_sec"] = round(st, 3)
            mapped["end_sec"] = round(en, 3)
            mapped["anchor_gap_sec"] = round(gap, 3)
            aligned.append(mapped)
        segments.append(
            {
                "start_sec": round(seg_start, 3),
                "end_sec": round(seg_end, 3),
                "offset_sec": round(off, 3),
                "score": round(seg_score, 4),
            }
        )

    if use_piecewise and len(timed) >= 8:
        mode = "piecewise"
        timed_sorted = sorted(timed, key=lambda x: float(x.get("start_sec", 0.0)))
        idx = 0
        while idx < len(timed_sorted):
            seg_start = float(timed_sorted[idx].get("start_sec", 0.0))
            target_lines = 5
            if idx > 0:
                prev_gap = seg_start - float(timed_sorted[idx - 1].get("start_sec", seg_start))
                if prev_gap > 3.0:
                    target_lines = 4
                elif prev_gap < 1.2:
                    target_lines = 6
            target_lines = max(4, min(6, target_lines))
            seg_items: list[dict[str, Any]] = []
            j = idx
            while j < len(timed_sorted) and len(seg_items) < target_lines:
                seg_items.append(timed_sorted[j])
                j += 1
            if not seg_items:
                idx = j + 1
                continue
            seg_end = float(seg_items[-1].get("end_sec", seg_items[-1].get("start_sec", seg_start) + 2.0))
            seg_offset, seg_score = find_best_offset(seg_items)
            apply_items(seg_items, seg_offset, seg_start, seg_end, seg_score)
            idx = j
    else:
        apply_items(timed, best_offset, 0.0, max((float(x.get("end_sec", 0.0)) for x in timed), default=0.0), best_score)

    aligned.sort(key=lambda x: float(x.get("start_sec", 0.0)))
    weighted_offset = float(round(sum(float(s["offset_sec"]) for s in segments) / max(1, len(segments)), 3))
    score = float(round((sum(closeness) / max(1, len(closeness))), 4))
    return aligned, weighted_offset, score, mode, segments


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
            raw = p.read_text(encoding="utf-8", errors="replace")
            timed = _parse_vtt_timed_lyrics(raw, "youtube_subtitles")
            text = _timed_lyrics_to_plain(timed) or _vtt_to_plain_lyrics(raw)
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
) -> tuple[str | None, str, list[dict[str, Any]], str]:
    """
    LRCLIB 우선 → (옵션) ffprobe 길이로 재시도 → 유튜브 설명 폴백.
    반환: (가사 텍스트, 출처, timed_lyrics, timed_source)
    """
    text, src = fetch_lyrics_from_lrclib(
        title, artist, uploader, duration_youtube, cache_dir=cache_dir
    )
    timed_lrclib, timed_lrclib_src = _fetch_lrclib_timed_lyrics(
        title, artist, uploader, duration_youtube if duration_youtube is not None else duration_audio
    )
    if text and text.strip():
        return text.strip(), src, timed_lrclib, timed_lrclib_src

    if duration_audio is not None:
        if duration_youtube is None or abs(float(duration_audio) - float(duration_youtube or 0)) > 1.0:
            text2, src2 = fetch_lyrics_from_lrclib(
                title, artist, uploader, duration_audio, cache_dir=cache_dir
            )
            if text2 and text2.strip():
                return text2.strip(), src2, timed_lrclib, timed_lrclib_src

    subs_dir = job_dir / "lyrics_subs"
    yt_sub = _youtube_subtitle_fallback_lyrics(url, subs_dir)
    if yt_sub and yt_sub.strip():
        timed_candidates = sorted(subs_dir.glob("*.ko-orig.vtt"), reverse=True) + sorted(
            subs_dir.glob("*.ko.vtt"), reverse=True
        )
        for p in timed_candidates:
            try:
                timed_sub = _parse_vtt_timed_lyrics(p.read_text(encoding="utf-8", errors="replace"), "youtube_subtitles")
            except Exception:
                continue
            if timed_sub:
                return yt_sub.strip(), "youtube_subtitles", timed_sub, "youtube_subtitles"
        return yt_sub.strip(), "youtube_subtitles", timed_lrclib, timed_lrclib_src

    fb = _description_fallback_lyrics(description)
    if fb:
        return fb, "youtube_description", timed_lrclib, timed_lrclib_src
    return None, "none", timed_lrclib, timed_lrclib_src


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


def _guess_capo_from_text(*texts: str | None) -> int:
    """제목/설명에서 capo(0~12) 추정. 없으면 0."""
    blob = " ".join(t for t in texts if t)
    for pat in (
        r"(?i)capo\s*[:=]?\s*(\d{1,2})",
        r"(?i)카포\s*(\d{1,2})",
        r"(?i)(\d{1,2})\s*카포",
        r"(?i)캡\s*o\s*(\d{1,2})",
        r"(?i)(\d{1,2})\s*fret",
    ):
        m = re.search(pat, blob)
        if m:
            v = int(m.group(1))
            if 0 <= v <= 12:
                return v
    return 0


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
            adj = score - CHORD_EXTRA_PENALTY * extra
            if adj > best_score + 1e-9:
                best_score = adj
                shape_root = (root - int(capo)) % 12
                best_label = f"{_pc_to_name(shape_root)}{suffix}"
    if best_label is None or best_score < total * CHORD_MIN_SCORE_RATIO:
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


def _parse_chord_label(label: str) -> tuple[int, str]:
    m = re.match(r"^([A-G](?:#|b)?)(.*)$", (label or "").strip())
    if not m:
        return 0, ""
    root_text = m.group(1)
    suffix = m.group(2) or ""
    pc_map = {
        "C": 0,
        "C#": 1,
        "Db": 1,
        "D": 2,
        "D#": 3,
        "Eb": 3,
        "E": 4,
        "F": 5,
        "F#": 6,
        "Gb": 6,
        "G": 7,
        "G#": 8,
        "Ab": 8,
        "A": 9,
        "A#": 10,
        "Bb": 10,
        "B": 11,
    }
    return pc_map.get(root_text, 0), suffix


def _quality_bucket_from_suffix(suffix: str) -> str:
    s = (suffix or "").lower()
    if "sus" in s:
        return "sus"
    if "dim" in s or "m7b5" in s:
        return "dim"
    if "maj7" in s:
        return "maj7"
    if s.startswith("m"):
        return "minor"
    return "major"


def _is_chord_diatonic_in_c_major(root_pc: int, suffix: str) -> bool:
    bucket = _quality_bucket_from_suffix(suffix)
    allowed: dict[int, set[str]] = {
        0: {"major", "maj7"},
        2: {"minor"},
        4: {"minor"},
        5: {"major", "maj7", "sus"},
        7: {"major"},
        9: {"minor"},
        11: {"dim"},
    }
    return bucket in allowed.get(root_pc % 12, set())


def _chord_candidate_scores_for_time_range(
    raw_notes: list[dict[str, Any]],
    t0: float,
    t1: float,
    capo: int,
) -> dict[str, float]:
    measure_len = max(1e-6, t1 - t0)
    weights = [0.0] * 12
    bass_prior = [0.0] * 12
    for n in raw_notes:
        ov = min(n["end"], t1) - max(n["start"], t0)
        if ov <= 0:
            continue
        vel = float(n.get("velocity", 64))
        vel_factor = max(0.25, min(1.2, vel / 96.0))
        dur_ratio = ov / measure_len
        dur_factor = CHORD_SHORT_NOTE_WEIGHT if dur_ratio < CHORD_SHORT_NOTE_RATIO else 1.0
        w = ov * vel_factor * dur_factor
        pc = int(n["pitch"]) % 12
        weights[pc] += w
        # 저음 우선 루트 prior (낮을수록 가중)
        low_boost = max(0.0, (72.0 - float(n["pitch"])) / 32.0)
        bass_prior[pc] += ov * low_boost

    total = sum(weights)
    if total < 1e-6:
        return {}

    candidate_scores: dict[str, float] = {}
    bass_norm = sum(bass_prior) or 1.0
    for root in range(12):
        for suffix, intervals in _CHORD_CANDIDATES:
            template = {(root + i) % 12 for i in intervals}
            score = sum(weights[p] for p in template)
            extra = sum(weights[p] for p in range(12) if p not in template)
            adj = score - CHORD_EXTRA_PENALTY * extra
            adj += CHORD_BASS_PRIOR_SCALE * total * (bass_prior[root] / bass_norm)
            if _is_chord_diatonic_in_c_major(root, suffix):
                adj += CHORD_KEY_CONTEXT_BONUS * total
            if adj < total * CHORD_MIN_SCORE_RATIO:
                continue
            shape_root = (root - int(capo)) % 12
            label = f"{_pc_to_name(shape_root)}{suffix}"
            candidate_scores[label] = max(candidate_scores.get(label, -1e9), float(adj))
    return candidate_scores


def _transition_penalty(prev_label: str, cur_label: str) -> float:
    prev_root, prev_suffix = _parse_chord_label(prev_label)
    cur_root, cur_suffix = _parse_chord_label(cur_label)
    root_jump = min((cur_root - prev_root) % 12, (prev_root - cur_root) % 12)
    penalty = CHORD_NGRAM_ROOT_JUMP_PENALTY * max(0, root_jump - 4)
    if _quality_bucket_from_suffix(prev_suffix) != _quality_bucket_from_suffix(cur_suffix):
        penalty += CHORD_NGRAM_QUALITY_SWITCH_PENALTY
    return float(penalty)


def _bar_chord_labels(
    raw_notes: list[dict[str, Any]],
    bars_info: list[tuple[float, float, int, int, float, int]],
    capo: int,
) -> list[str]:
    if not bars_info:
        return []
    per_bar: list[dict[str, float]] = []
    for bs, be, *_r in bars_info:
        cand = _chord_candidate_scores_for_time_range(raw_notes, bs, be, capo)
        per_bar.append(cand)

    states: list[list[str]] = []
    for c in per_bar:
        keys = sorted(c.keys(), key=lambda k: c[k], reverse=True)
        if not keys:
            keys = ["?"]
        states.append(keys[:6])

    dp: list[dict[str, float]] = []
    back: list[dict[str, str | None]] = []
    for i, labels in enumerate(states):
        dp.append({})
        back.append({})
        for lab in labels:
            base_score = per_bar[i].get(lab, -0.35 if lab == "?" else -1e6)
            if i == 0:
                dp[i][lab] = base_score
                back[i][lab] = None
                continue
            best = -1e18
            best_prev: str | None = None
            for prev_lab, prev_score in dp[i - 1].items():
                penalty = 0.0 if lab == "?" or prev_lab == "?" else _transition_penalty(prev_lab, lab)
                score = prev_score + base_score - penalty
                if score > best:
                    best = score
                    best_prev = prev_lab
            dp[i][lab] = best
            back[i][lab] = best_prev

    last_idx = len(states) - 1
    best_last = max(dp[last_idx].keys(), key=lambda k: dp[last_idx][k])
    out: list[str] = [best_last]
    cur = best_last
    for i in range(last_idx, 0, -1):
        prev = back[i].get(cur)
        out.append(prev if prev else "?")
        cur = prev if prev else "?"
    out.reverse()
    filled: list[str] = []
    prev_lab: str | None = None
    for lab in out:
        if lab == "?":
            filled.append(prev_lab or "?")
        else:
            filled.append(lab)
            prev_lab = lab
    return filled


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


def _strip_dy_from_alphatex_note_token(s: str) -> str:
    return re.sub(r"\s+\{dy\s+[^}]+\}\s*$", "", s).strip()


def _greedy_decompose_duration_units(units: float) -> list[int]:
    """16분음표 단위 길이를 :1..:32 토큰 분모 리스트로 분해한다."""
    dens_order = [1, 2, 4, 8, 16, 32]
    rem = float(units)
    out: list[int] = []
    eps = 1e-3
    guard = 0
    while rem > eps and guard < 20000:
        guard += 1
        placed = False
        for den in dens_order:
            u = 16.0 / den
            if rem + 1e-6 >= u:
                out.append(den)
                rem -= u
                placed = True
                break
        if not placed:
            out.append(32)
            rem -= 0.5
    return out


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


def _separate_demucs(mp3_path: Path, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "demucs.separate", "-n", "htdemucs", "--mp3", "-o", str(out_dir), str(mp3_path)])
    # demucs output: <out_dir>/htdemucs/<track_name>/*.mp3
    candidates = sorted((out_dir / "htdemucs").glob("*"))
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


def _ensure_flat_guitar_stem_mp3(stems: dict[str, Path], stems_root: Path) -> Path:
    """
    Demucs htdemucs는 보통 vocals/drums/bass/other 만 내보내고 파일명 `guitar`는 없다.
    Basic Pitch·onset에 쓰는 트랙(other 또는 일부 모델의 guitar)을 `stems/guitar.mp3`로 복사해
    작업 폴더에서 분리 기타 음원을 바로 찾을 수 있게 한다.
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
    midi_out.parent.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "basic_pitch.predict", str(midi_out.parent), str(guitar_audio)])
    produced = sorted(midi_out.parent.glob("*.mid"))
    if not produced:
        raise RuntimeError("Basic Pitch 변환 결과 MIDI 파일을 찾지 못했습니다.")
    produced[0].replace(midi_out)
    return midi_out


def _count_non_drum_midi_notes(midi: pretty_midi.PrettyMIDI) -> int:
    return sum(len(inst.notes) for inst in midi.instruments if not inst.is_drum)


def _cleanup_transcribed_midi(
    midi: pretty_midi.PrettyMIDI,
    *,
    enabled: bool = MIDI_CLEANUP_ENABLED,
    min_duration_sec: float = MIDI_CLEANUP_MIN_DURATION_SEC,
    duplicate_start_tolerance_sec: float = MIDI_CLEANUP_DUPLICATE_START_TOLERANCE_SEC,
    velocity_floor: int = MIDI_CLEANUP_VELOCITY_FLOOR,
    velocity_relative_ratio: float = MIDI_CLEANUP_VELOCITY_RELATIVE_RATIO,
    cleanup_strength: int = 1,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "enabled": bool(enabled),
        "min_duration_sec": float(min_duration_sec),
        "duplicate_start_tolerance_sec": float(duplicate_start_tolerance_sec),
        "velocity_floor": int(velocity_floor),
        "velocity_relative_ratio": float(velocity_relative_ratio),
        "raw_midi_note_count": _count_non_drum_midi_notes(midi),
        "cleaned_midi_note_count": 0,
        "removed_short_note_count": 0,
        "merged_duplicate_note_count": 0,
        "removed_velocity_note_count": 0,
        "fixed_invalid_note_count": 0,
    }
    if not enabled:
        stats["cleaned_midi_note_count"] = stats["raw_midi_note_count"]
        return stats

    min_dur = max(1e-3, float(min_duration_sec))
    dup_tol = max(0.0, float(duplicate_start_tolerance_sec))
    strength = max(1, int(cleanup_strength))
    density_peak_global = 0
    for inst in midi.instruments:
        if inst.is_drum or not inst.notes:
            continue
        # 한국어 주석: 잘못된 end/start를 먼저 보정해 후속 필터가 안전하게 동작하도록 한다.
        valid_notes: list[pretty_midi.Note] = []
        for n in inst.notes:
            if n.end <= n.start:
                n.end = n.start + 1e-3
                stats["fixed_invalid_note_count"] += 1
            valid_notes.append(n)

        if not valid_notes:
            inst.notes = []
            continue

        max_vel = max(int(n.velocity) for n in valid_notes)
        vel_threshold = max(int(velocity_floor), int(round(max_vel * float(velocity_relative_ratio))))
        starts = sorted(float(n.start) for n in valid_notes)
        # 한국어 주석: 고밀도 구간일수록 짧은/약한 노트를 더 강하게 정리한다.
        density_score = 0
        if starts:
            j = 0
            for i, st in enumerate(starts):
                while st - starts[j] > 0.60:
                    j += 1
                density_score = max(density_score, i - j + 1)
        density_peak_global = max(density_peak_global, density_score)
        dense_factor = 1.0
        if density_score >= 16:
            dense_factor = 1.65
        elif density_score >= 12:
            dense_factor = 1.45
        elif density_score >= 8:
            dense_factor = 1.25
        dense_factor += 0.08 * float(max(0, strength - 1))
        adaptive_min_dur = min(0.20, min_dur * dense_factor)
        adaptive_dup_tol = min(0.16, dup_tol * (1.25 if dense_factor > 1.0 else 1.0) * (1.0 + 0.10 * float(strength - 1)))
        adaptive_vel_threshold = min(
            118,
            int(round(vel_threshold * (1.20 if dense_factor > 1.0 else 1.0) * (1.0 + 0.07 * float(strength - 1)))),
        )
        dur_filtered: list[pretty_midi.Note] = []
        for n in valid_notes:
            duration = float(n.end) - float(n.start)
            if duration < adaptive_min_dur:
                stats["removed_short_note_count"] += 1
                continue
            if int(n.velocity) < adaptive_vel_threshold:
                stats["removed_velocity_note_count"] += 1
                continue
            dur_filtered.append(n)

        by_pitch: dict[int, list[pretty_midi.Note]] = {}
        for n in dur_filtered:
            by_pitch.setdefault(int(n.pitch), []).append(n)

        merged_notes: list[pretty_midi.Note] = []
        for arr in by_pitch.values():
            arr_sorted = sorted(arr, key=lambda x: (float(x.start), -int(x.velocity), float(x.end)))
            if not arr_sorted:
                continue
            cur = arr_sorted[0]
            for nxt in arr_sorted[1:]:
                if abs(float(nxt.start) - float(cur.start)) <= adaptive_dup_tol:
                    cur.start = min(float(cur.start), float(nxt.start))
                    cur.end = max(float(cur.end), float(nxt.end))
                    cur.velocity = max(int(cur.velocity), int(nxt.velocity))
                    stats["merged_duplicate_note_count"] += 1
                else:
                    merged_notes.append(cur)
                    cur = nxt
            merged_notes.append(cur)

        merged_notes.sort(key=lambda x: (float(x.start), int(x.pitch), -int(x.velocity)))
        # 한국어 주석: 강한 모드에서는 초단기 잔노트를 한 번 더 제거해 밀도를 낮춘다.
        residual_min_dur = max(1e-3, adaptive_min_dur * (0.55 if strength >= 2 else 0.40))
        final_notes: list[pretty_midi.Note] = []
        for n in merged_notes:
            if (float(n.end) - float(n.start)) < residual_min_dur:
                stats["removed_short_note_count"] += 1
                continue
            final_notes.append(n)
        inst.notes = final_notes

    stats["cleaned_midi_note_count"] = _count_non_drum_midi_notes(midi)
    stats["density_peak_per_600ms"] = int(density_peak_global)
    return stats


def _read_compare_f1(compare_report_path: Path) -> float:
    try:
        payload = json.loads(compare_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    after_export = payload.get("compare_after_export") if isinstance(payload, dict) else {}
    before_refine = payload.get("compare_before_refine") if isinstance(payload, dict) else {}
    f1 = 0.0
    if isinstance(after_export, dict):
        f1 = max(f1, float(after_export.get("f1_onset_symmetric", 0.0)))
    if isinstance(before_refine, dict):
        f1 = max(f1, float(before_refine.get("f1_onset_symmetric", 0.0)))
    return float(f1)


def _score_candidate_components(
    render_stats: dict[str, Any],
    cleaned_ratio: float,
    compare_f1: float,
) -> dict[str, float]:
    token_after = float(render_stats.get("token_counts", {}).get("after", 99999.0))
    duration32 = float(render_stats.get("duration_32_ratio_after_pct", 100.0))
    bar_density = float(render_stats.get("bar_density_p95", 999.0))
    meter_fail = float(render_stats.get("meter_integrity", {}).get("fail", 1))
    validator_fail = 0.0 if bool(render_stats.get("validator_passed", False)) else 1.0
    voice_preservation = float(render_stats.get("voice_preservation_score", 0.0))
    penalty_fret_jump_p95 = float(render_stats.get("penalty_fret_jump_p95", 0.0))
    penalty_string_cross_rate = float(render_stats.get("penalty_string_cross_rate", 0.0))
    penalty_attack_burst = float(render_stats.get("penalty_attack_burst", 0.0))
    penalty_bar_overflow = float(render_stats.get("penalty_bar_overflow", 0.0))
    penalty_duration_fragmentation = float(render_stats.get("penalty_duration_fragmentation", 0.0))
    reward_phrase_continuity = float(render_stats.get("phrase_continuity_score", 0.0))
    parts = {
        "penalty_duration32": max(0.0, duration32 - 20.0) * 0.06,
        "penalty_token_after": max(0.0, token_after - 180.0) * 0.004,
        "penalty_bar_density": max(0.0, bar_density - 24.0) * 0.03,
        "penalty_cleaned_ratio": max(0.0, cleaned_ratio - 0.72) * 1.1,
        "penalty_meter_fail": meter_fail * 6.0,
        "penalty_validator_fail": validator_fail * 12.0,
        "penalty_fret_jump_p95": penalty_fret_jump_p95,
        "penalty_string_cross_rate": penalty_string_cross_rate,
        "penalty_attack_burst": penalty_attack_burst,
        "penalty_bar_overflow": penalty_bar_overflow,
        "penalty_duration_fragmentation": penalty_duration_fragmentation,
        "reward_voice_preservation": max(0.0, voice_preservation) * 1.8,
        "reward_compare_f1": max(0.0, compare_f1) * 2.2,
        "reward_phrase_continuity": max(0.0, reward_phrase_continuity) * 1.6,
    }
    parts["playability_penalty_sum"] = (
        parts["penalty_fret_jump_p95"] + parts["penalty_string_cross_rate"] + parts["penalty_attack_burst"]
    )
    parts["total_score"] = (
        parts["penalty_duration32"]
        + parts["penalty_token_after"]
        + parts["penalty_bar_density"]
        + parts["penalty_cleaned_ratio"]
        + parts["penalty_meter_fail"]
        + parts["penalty_validator_fail"]
        + parts["penalty_fret_jump_p95"]
        + parts["penalty_string_cross_rate"]
        + parts["penalty_attack_burst"]
        + parts["penalty_bar_overflow"]
        + parts["penalty_duration_fragmentation"]
        - parts["reward_voice_preservation"]
        - parts["reward_compare_f1"]
        - parts["reward_phrase_continuity"]
    )
    return {k: float(round(v, 6)) for k, v in parts.items()}


def _score_candidate(
    render_stats: dict[str, Any],
    cleaned_ratio: float,
    compare_f1: float,
) -> float:
    return float(_score_candidate_components(render_stats, cleaned_ratio, compare_f1)["total_score"])


def _voice_aware_compact_note_events(
    note_events: list[dict[str, Any]],
    *,
    melody_ioi_floor_sec: float,
    accompaniment_ioi_floor_sec: float,
) -> list[dict[str, Any]]:
    if not note_events:
        return []
    events = [dict(n) for n in note_events]
    for n in events:
        if "pitch" not in n:
            n["pitch"] = int(GUITAR_OPEN_MIDI[int(n["string"]) - 1]) + int(n["fret"])
    events = sorted(events, key=lambda x: (float(x["start"]), -int(x["pitch"]), -int(x["velocity"])))

    melody_ids: set[int] = set()
    i = 0
    while i < len(events):
        st = float(events[i]["start"])
        j = i + 1
        bucket_best = i
        while j < len(events) and float(events[j]["start"]) <= st + ONSET_TOLERANCE_SEC:
            if int(events[j]["pitch"]) > int(events[bucket_best]["pitch"]):
                bucket_best = j
            j += 1
        melody_ids.add(bucket_best)
        i = j

    compacted: list[dict[str, Any]] = []
    last_by_pos: dict[tuple[int, int], dict[str, Any]] = {}
    last_by_voice: dict[str, dict[str, Any]] = {}
    for idx, n in enumerate(events):
        pos = (int(n["string"]), int(n["fret"]))
        is_melody = idx in melody_ids
        voice_key = "melody" if is_melody else "accompaniment"
        floor = float(melody_ioi_floor_sec if is_melody else accompaniment_ioi_floor_sec)

        prev_pos = last_by_pos.get(pos)
        if prev_pos is not None:
            ioi_pos = float(n["start"]) - float(prev_pos["start"])
            if ioi_pos < floor:
                prev_pos["end"] = max(float(prev_pos["end"]), float(n["end"]))
                prev_pos["velocity"] = max(int(prev_pos["velocity"]), int(n["velocity"]))
                continue

        prev_voice = last_by_voice.get(voice_key)
        if prev_voice is not None:
            ioi_voice = float(n["start"]) - float(prev_voice["start"])
            if ioi_voice < floor and int(prev_voice["pitch"]) == int(n["pitch"]):
                prev_voice["end"] = max(float(prev_voice["end"]), float(n["end"]))
                prev_voice["velocity"] = max(int(prev_voice["velocity"]), int(n["velocity"]))
                continue

        compacted.append(n)
        last_by_pos[pos] = n
        last_by_voice[voice_key] = n

    return sorted(compacted, key=lambda x: (float(x["start"]), int(x["string"]), int(x["fret"])))


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
    cost = abs(prev_fret - fret) + 0.50 * abs(prev_string - string)

    # 개방현 우선(자연스러운 연주/손가락 부담 완화)
    if fret == 0:
        cost -= 0.25

    # 과도한 점프 페널티
    jump = abs(prev_fret - fret)
    if jump > 10:
        cost += (jump - 10) * 1.2

    return float(cost)


def _reduce_note_density(
    raw_notes: list[dict[str, Any]],
    *,
    quarter_sec: float,
) -> list[dict[str, Any]]:
    if not raw_notes:
        return raw_notes

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
            else:
                merged.append(cur)
                cur = dict(nxt)
        merged.append(cur)

    # 3-D: 지속 길이 상한 (최대 N박)
    clamped: list[dict[str, Any]] = []
    max_sustain_sec = quarter_sec * MAX_SUSTAIN_BEATS
    for n in sorted(merged, key=lambda x: (float(x["start"]), int(x["pitch"]))):
        start = float(n["start"])
        end = float(n["end"])
        cap1 = start + max_sustain_sec
        new_end = min(end, cap1)
        if new_end <= start + 1e-3:
            continue
        clamped.append(
            {
                "pitch": int(n["pitch"]),
                "velocity": int(n["velocity"]),
                "start": start,
                "end": new_end,
            }
        )
    return clamped if clamped else raw_notes


def _quantized_beats_from_midi(
    midi: pretty_midi.PrettyMIDI,
    tempo: float,
) -> tuple[list[dict[str, Any]], float]:
    """
    MIDI note start/end를 1/16 단위로 기본 양자화하고,
    필요할 경우 1/32 단위까지 적응적으로 사용한다.
    """

    quarter = 60.0 / max(1.0, tempo)
    step_16 = quarter / 4.0  # 1/16

    # S9: 16분 고정. 32분 그리드는 과밀 표기를 유발하므로 비활성화한다.
    melodic_instruments = [inst for inst in midi.instruments if not inst.is_drum and inst.notes]
    if not melodic_instruments:
        melodic_instruments = [inst for inst in midi.instruments if inst.notes]

    candidate_raw_notes: list[dict[str, Any]] = []
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
                    "pitch": int(note.pitch),
                    "velocity": int(note.velocity),
                    "start": float(note.start),
                    "end": float(note.end),
                }
            )

    candidate_raw_notes = _reduce_note_density(
        candidate_raw_notes,
        quarter_sec=quarter,
    )

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

    step = step_16

    # slot -> raw note list (여기서 아직 string/fret은 DP 후에 결정)
    slots: dict[int, list[dict[str, Any]]] = {}
    for n in candidate_raw_notes:
        slot = max(0, int(round(float(n["start"]) / step)))
        start = slot * step
        end_slot = max(slot + 1, int(round(float(n["end"]) / step)))
        end = end_slot * step

        slots.setdefault(slot, []).append(
            {
                "pitch": n["pitch"],
                "velocity": n["velocity"],
                "start": float(start),
                "end": float(end),
            }
        )

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
        lead_pitch = slot_leads[k]["pitch"]
        cand = _midi_pitch_to_candidate_positions(lead_pitch)
        if not cand:
            cand = [_midi_note_to_string_fret(lead_pitch)]
        lead_candidates[k] = cand

    # Viterbi DP: 각 slot의 lead pos를 선택한다.
    dp: dict[tuple[int, int], float] = {}
    back: dict[int, dict[tuple[int, int], tuple[int, int] | None]] = {}
    prev_slot_keys = slot_keys[0:1]
    first_k = prev_slot_keys[0]
    for pos in lead_candidates[first_k]:
        dp[pos] = 0.0
        back.setdefault(first_k, {})[pos] = None
    for k in slot_keys[1:]:
        new_dp: dict[tuple[int, int], float] = {}
        back.setdefault(k, {})
        for pos in lead_candidates[k]:
            best_cost = float("inf")
            best_prev_pos: tuple[int, int] | None = None
            for prev_pos, prev_cost in dp.items():
                cost = prev_cost + _position_transition_cost(prev_pos, pos)
                if cost < best_cost:
                    best_cost = cost
                    best_prev_pos = prev_pos
            new_dp[pos] = best_cost
            back[k][pos] = best_prev_pos
        dp = new_dp
        prev_k = k

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

    # slot 별 note mapping (lead은 DP 결과, 나머지는 직전 lead pos를 기준으로 그리디)
    beats: list[dict[str, Any]] = []
    first_slot_time = slot_keys[0] * step
    if first_slot_time > 0:
        beats.append({"time": 0.0, "chord": None, "lyric": None, "notes": []})

    prev_lead_pos: tuple[int, int] = best_lead_pos[slot_keys[0]]
    for k in slot_keys:
        time_value = float(k * step)
        notes = slots[k]
        mapped_notes: list[dict[str, Any]] = []
        lead_note = slot_leads[k]
        for n in notes:
            if n is lead_note:
                string_no, fret = best_lead_pos[k]
                mapped_notes.append(
                    {
                        "string": int(string_no),
                        "fret": int(fret),
                        "start": float(n["start"]),
                        "end": float(n["end"]),
                        "velocity": int(n["velocity"]),
                    }
                )
                continue

            candidates = _midi_pitch_to_candidate_positions(n["pitch"])
            if not candidates:
                candidates = [_midi_note_to_string_fret(n["pitch"])]
            best_pos = min(candidates, key=lambda pos: _position_transition_cost(prev_lead_pos, pos))
            string_no, fret = best_pos
            mapped_notes.append(
                {
                    "string": int(string_no),
                    "fret": int(fret),
                    "start": float(n["start"]),
                    "end": float(n["end"]),
                    "velocity": int(n["velocity"]),
                }
            )

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
            :MAX_NOTES_PER_SLOT
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

    # 한국어 주석: 같은 string/fret 재타격 시 이전 음을 조기 종료해 sustain 겹침을 완화한다.
    last_by_position: dict[tuple[int, int], dict[str, Any]] = {}
    for beat in beats:
        beat_start = float(beat.get("time", 0.0))
        for n in beat.get("notes", []):
            key = (int(n["string"]), int(n["fret"]))
            prev = last_by_position.get(key)
            if prev is not None and float(prev["end"]) > beat_start + 1e-3:
                prev["end"] = max(float(prev["start"]) + 1e-3, beat_start + (SUSTAIN_RELEASE_SEC * 0.25))
            last_by_position[key] = n

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
    tab_output_dir: Path | None = None,
    render_stats_out: dict[str, Any] | None = None,
    duration_32_ratio_target_pct: float = DURATION_32_RATIO_TARGET_PCT,
    bar_32_ratio_limit_pct: float = BAR_32_RATIO_LIMIT_PCT,
    bar_32_max_count: int = 4,
    bar_attack_max_count: int = BAR_ATTACK_MAX_COUNT,
    chord_first_simplify: bool = CHORD_FIRST_SIMPLIFY,
    accompaniment_limit: int = 2,
    melody_ioi_floor_sec: float = 0.055,
    accompaniment_ioi_floor_sec: float = 0.105,
) -> str:
    midi = pretty_midi.PrettyMIDI(str(midi_path))
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

    beats, _grid_step_sec = _quantized_beats_from_midi(midi, tempo0)
    beats = sorted(beats, key=lambda b: float(b.get("time", 0.0)))

    suppress_mid_bar_midi_tempo = tempo_override is not None

    note_events: list[dict[str, Any]] = []
    for b in beats:
        for n in b.get("notes", []):
            if not n:
                continue
            if n.get("start") is None or n.get("end") is None:
                continue
            note_events.append(
                {
                    "string": int(n["string"]),
                    "fret": int(n["fret"]),
                    "start": float(n["start"]),
                    "end": float(n["end"]),
                    "velocity": int(n.get("velocity", 64)),
                    "pitch": int(GUITAR_OPEN_MIDI[int(n["string"]) - 1]) + int(n["fret"]),
                }
            )

    if note_events:
        note_events, _ref_passes = refine_note_events_with_reference_midi(
            note_events, midi_path, max_passes=2
        )
        note_events = _voice_aware_compact_note_events(
            note_events,
            melody_ioi_floor_sec=float(melody_ioi_floor_sec),
            accompaniment_ioi_floor_sec=float(accompaniment_ioi_floor_sec),
        )
    analysis_note_events = [dict(n) for n in note_events]

    def _build_render_note_events_with_adaptive_hold(
        events: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
        if not events:
            return [], {
                "melody": {"min_hold_sec": 0.14, "max_hold_sec": 0.62},
                "bass": {"min_hold_sec": 0.12, "max_hold_sec": 0.52},
                "accompaniment": {"min_hold_sec": 0.08, "max_hold_sec": 0.34},
            }
        profile = {
            "melody": {"min_hold_sec": 0.14, "max_hold_sec": 0.62},
            "bass": {"min_hold_sec": 0.12, "max_hold_sec": 0.52},
            "accompaniment": {"min_hold_sec": 0.08, "max_hold_sec": 0.34},
        }
        grouped: dict[float, list[dict[str, Any]]] = {}
        for n in sorted(events, key=lambda x: (float(x["start"]), int(x.get("pitch", 0)))):
            st = round(float(n["start"]), 6)
            grouped.setdefault(st, []).append(dict(n))
        onsets = sorted(grouped.keys())
        out: list[dict[str, Any]] = []
        for idx, onset in enumerate(onsets):
            cur = grouped[onset]
            next_onset = onsets[idx + 1] if idx + 1 < len(onsets) else None
            margin = 0.015
            if next_onset is not None and next_onset > onset:
                margin = min(0.02, max(0.008, (next_onset - onset) * 0.12))
            pitches = [int(it.get("pitch", 0)) for it in cur]
            top_pitch = max(pitches) if pitches else -999
            low_pitch = min(pitches) if pitches else 999
            for n in cur:
                nn = dict(n)
                p = int(nn.get("pitch", 0))
                role = "accompaniment"
                if p == top_pitch:
                    role = "melody"
                elif p == low_pitch:
                    role = "bass"
                min_hold = float(profile[role]["min_hold_sec"])
                max_hold = float(profile[role]["max_hold_sec"])
                ceiling = float(nn["start"]) + max_hold
                if next_onset is not None:
                    ceiling = min(ceiling, float(next_onset) - margin)
                new_end = max(float(nn["start"]) + min_hold, min(float(nn["end"]), ceiling))
                nn["end"] = max(float(nn["start"]) + 1e-3, new_end)
                out.append(nn)
        return sorted(out, key=lambda x: (float(x["start"]), int(x["string"]), int(x["fret"]))), profile

    render_note_events, voice_hold_profile = _build_render_note_events_with_adaptive_hold(analysis_note_events)
    note_events = render_note_events
    play_jump_values: list[float] = []
    play_string_cross = 0
    play_total_pairs = 0
    if len(note_events) >= 2:
        ordered = sorted(note_events, key=lambda x: (float(x["start"]), int(x["string"]), int(x["fret"])))
        prev = ordered[0]
        for cur in ordered[1:]:
            play_total_pairs += 1
            jump = abs(int(cur["fret"]) - int(prev["fret"]))
            play_jump_values.append(float(jump))
            if int(cur["string"]) != int(prev["string"]):
                play_string_cross += 1
            prev = cur

    base_den = 16
    eps = 1e-6

    ts_pairs: list[tuple[float, tuple[int, int]]] = [(t, (n, d)) for t, n, d in ts_segments]
    raw_notes = _raw_guitar_notes_from_midi(midi)
    max_q = max([n["end"] for n in note_events], default=0.0)
    max_raw = max([n["end"] for n in raw_notes], default=0.0)
    max_end = max(max_q, max_raw, 0.01)

    # 가변 마디 길이(박자표·템포) 타임라인
    bars_info = _compute_bars_info(midi, max_end, bpm_override=tempo_override)
    bar_chords = _bar_chord_labels(raw_notes, bars_info, int(capo))
    chord_order_unique: list[str] = []
    _seen_ch: set[str] = set()
    for _lbl in bar_chords:
        if _lbl not in _seen_ch:
            _seen_ch.add(_lbl)
            chord_order_unique.append(_lbl)
    chord_def_block = _alphatex_chord_definitions_block(chord_order_unique)
    capo_line = f"\\capo {int(capo)}\n" if int(capo) > 0 else ""

    # 한국어 주석: 온셋 중심 렌더 모드(기본 True), 필요 시 기존 경계 방식 fallback.
    ATTACK_ONLY_RENDER = True

    def uniq_sorted(values: list[float]) -> list[float]:
        values_sorted = sorted(values)
        out: list[float] = []
        for v in values_sorted:
            if not out or abs(v - out[-1]) > 1e-5:
                out.append(round(v, 6))
        return out

    def build_onset_boundaries() -> list[float]:
        boundaries: set[float] = {0.0, last_bar_end}
        for bs, be, *_r in bars_info:
            boundaries.add(float(bs))
            boundaries.add(float(be))
        if ATTACK_ONLY_RENDER:
            for n in note_events:
                boundaries.add(float(n["start"]))
        else:
            for n in note_events:
                boundaries.add(float(n["start"]))
                boundaries.add(float(n["end"]))
        return uniq_sorted(list(boundaries))

    def _token_duration_units(tok: str) -> float:
        stripped = tok.lstrip()
        if not stripped.startswith(":"):
            return float(16.0 / base_den)
        m = re.match(r"^:(\d+)\b", stripped)
        if not m:
            return float(16.0 / base_den)
        den = max(1, int(m.group(1)))
        return float(16.0 / den)

    def _parse_token(tok: str) -> tuple[int, str]:
        stripped = tok.strip()
        m = re.match(r"^:(\d+)\s+(.+)$", stripped)
        if m:
            return max(1, int(m.group(1))), m.group(2).strip()
        return base_den, stripped

    def _format_token(den: int, content: str) -> str:
        if den == base_den:
            return content
        return f":{den} {content}"

    def _merge_two_32(content: str) -> str:
        if content == "r":
            return ":16 r"
        return f":16 {content}"

    def _is_weak_token_content(content: str) -> bool:
        lowered = content.lower()
        if content.strip() == "r":
            return True
        return "{dy ppp}" in lowered or "{dy pp}" in lowered or "{dy p}" in lowered

    def _units_to_den(units: float) -> int | None:
        table = {
            0.5: 32,
            1.0: 16,
            2.0: 8,
            4.0: 4,
            8.0: 2,
            16.0: 1,
        }
        for k, v in table.items():
            if abs(units - k) <= 1e-6:
                return v
        return None

    def _optimize_bar_tokens_for_readability(
        tokens: list[str],
        snapshots: list[tuple[tuple[int, int], ...]],
        measure_units_target: float,
    ) -> tuple[list[str], list[tuple[tuple[int, int], ...]]]:
        if not tokens:
            return tokens, snapshots
        if len(tokens) != len(snapshots):
            return tokens, snapshots

        # 한국어 주석: 약한 32분 토큰을 먼저 정리해 뒤 단계 병합 효율을 높인다.
        lowered_tokens: list[str] = []
        lowered_snaps: list[tuple[tuple[int, int], ...]] = []
        for tok in tokens:
            den, content = _parse_token(tok)
            if den == 32 and "{dy ppp}" in content:
                lowered_tokens.append(_format_token(den, _strip_dy_from_alphatex_note_token(content)))
            elif den == 32 and ("{dy pp}" in content or "{dy p}" in content):
                lowered_tokens.append(":32 r")
            else:
                lowered_tokens.append(tok)
        lowered_snaps.extend(snapshots)

        packed: list[str] = []
        packed_snaps: list[tuple[tuple[int, int], ...]] = []
        i = 0
        while i < len(lowered_tokens):
            cur = lowered_tokens[i]
            den, content = _parse_token(cur)
            if den == 32:
                j = i + 1
                while j < len(lowered_tokens):
                    den_j, content_j = _parse_token(lowered_tokens[j])
                    if den_j != 32:
                        break
                    if lowered_snaps[j] != lowered_snaps[i]:
                        break
                    if content_j != content and not (_is_weak_token_content(content_j) or _is_weak_token_content(content)):
                        break
                    j += 1
                count = j - i
                while count >= 2:
                    if content == "r":
                        merged_content = "r"
                    else:
                        merged_content = content if not _is_weak_token_content(content) else _strip_dy_from_alphatex_note_token(content)
                    packed.append(_merge_two_32(merged_content))
                    packed_snaps.append(lowered_snaps[i])
                    count -= 2
                if count == 1:
                    packed.append(_format_token(32, content))
                    packed_snaps.append(lowered_snaps[i])
                i = j
                continue
            packed.append(cur)
            packed_snaps.append(lowered_snaps[i])
            i += 1

        # 한국어 주석: 동일 snapshot/동일 내용의 인접 토큰은 길이 확장으로 재압축한다.
        merged_tokens: list[str] = []
        merged_snaps: list[tuple[tuple[int, int], ...]] = []
        i = 0
        while i < len(packed):
            den, content = _parse_token(packed[i])
            if i + 1 < len(packed):
                den2, content2 = _parse_token(packed[i + 1])
                if (
                    packed_snaps[i] == packed_snaps[i + 1]
                    and den == den2
                    and content == content2
                    and den > 1
                ):
                    merged_tokens.append(_format_token(max(1, den // 2), content))
                    merged_snaps.append(packed_snaps[i])
                    i += 2
                    continue
            merged_tokens.append(packed[i])
            merged_snaps.append(packed_snaps[i])
            i += 1

        units_after = sum(_token_duration_units(tok) for tok in merged_tokens)
        if abs(float(units_after) - float(measure_units_target)) > 1e-3:
            return tokens, snapshots
        attack_cap = max(1, int(bar_attack_max_count))
        while True:
            attack_indices = [
                i for i, tok in enumerate(merged_tokens) if _parse_token(tok)[1] != "r"
            ]
            if len(attack_indices) <= attack_cap:
                break
            changed = False
            for idx in attack_indices:
                if idx + 1 >= len(merged_tokens):
                    continue
                den1, c1 = _parse_token(merged_tokens[idx])
                den2, c2 = _parse_token(merged_tokens[idx + 1])
                if merged_snaps[idx] != merged_snaps[idx + 1]:
                    continue
                if not (_is_weak_token_content(c1) or _is_weak_token_content(c2)):
                    continue
                units = _token_duration_units(merged_tokens[idx]) + _token_duration_units(merged_tokens[idx + 1])
                merged_den = _units_to_den(units)
                if merged_den is None:
                    continue
                preferred = c1 if not _is_weak_token_content(c1) else c2
                merged_tokens[idx : idx + 2] = [_format_token(merged_den, preferred)]
                merged_snaps[idx : idx + 2] = [merged_snaps[idx]]
                changed = True
                break
            if not changed:
                weak_idx = next(
                    (i for i in attack_indices if _is_weak_token_content(_parse_token(merged_tokens[i])[1])),
                    attack_indices[-1],
                )
                merged_tokens[weak_idx] = _format_token(_parse_token(merged_tokens[weak_idx])[0], "r")
                changed = True
            if not changed:
                break
        return merged_tokens, merged_snaps

    def merge_redundant_sustain_segments(
        chunks: list[tuple[float, float, tuple[tuple[int, int], ...], str, str]]
    ) -> tuple[list[list[Any]], int]:
        merged_rows_local: list[list[Any]] = []
        repeated_pairs = 0
        for t0b, t1b, snap, full_tok, base_tok in chunks:
            if merged_rows_local and snap == merged_rows_local[-1][2] and abs(t0b - merged_rows_local[-1][1]) < 1e-5:
                merged_rows_local[-1][1] = t1b
                repeated_pairs += 1
            else:
                merged_rows_local.append([t0b, t1b, snap, full_tok, base_tok])
        return merged_rows_local, repeated_pairs

    def _build_chunks_from_boundaries(
        boundaries: list[float],
    ) -> list[tuple[float, float, tuple[tuple[int, int], ...], str, str]]:
        prev_dy_local: str | None = None
        out_chunks: list[tuple[float, float, tuple[tuple[int, int], ...], str, str]] = []
        for idx in range(len(boundaries) - 1):
            t0b = float(boundaries[idx])
            t1b = float(boundaries[idx + 1])
            if t1b <= t0b + eps:
                continue
            snap = _tab_snapshot_key(note_events, t0b, eps)
            full_tok, prev_dy_local = active_content_with_dy(t0b, prev_dy_local)
            base_tok = _strip_dy_from_alphatex_note_token(full_tok)
            out_chunks.append((t0b, t1b, snap, full_tok, base_tok))
        return out_chunks

    def _estimate_counts_for_rows(rows: list[list[Any]]) -> tuple[int, int]:
        sim_bar_idx = 0
        sim_bar_units = 0.0
        sim_tokens = 0
        sim_repeat = 0
        prev_snap: tuple[tuple[int, int], ...] | None = None
        for row in rows:
            st, en, snap = float(row[0]), float(row[1]), row[2]
            ct = st
            while ct < en - eps and sim_bar_idx < len(bars_info):
                while sim_bar_idx < len(bars_info) and ct >= float(bars_info[sim_bar_idx][1]) - eps:
                    sim_bar_idx += 1
                    sim_bar_units = 0.0
                if sim_bar_idx >= len(bars_info):
                    break
                _bs_r, be_r, _nr, _dr, bpm_r, measure_units_target = bars_info[sim_bar_idx]
                base_unit_sec = (60.0 / max(20.0, bpm_r)) / 4.0
                chunk_end = min(en, float(be_r))
                chunk_sec = max(0.0, chunk_end - ct)
                if chunk_sec <= eps:
                    ct = chunk_end
                    continue
                rem_u = chunk_sec / base_unit_sec
                while rem_u > 1e-6 and sim_bar_idx < len(bars_info):
                    room = float(measure_units_target) - sim_bar_units
                    if room <= 1e-9:
                        sim_bar_idx += 1
                        sim_bar_units = 0.0
                        if sim_bar_idx < len(bars_info):
                            measure_units_target = bars_info[sim_bar_idx][5]
                        continue
                    nu = 0.0
                    for d in (1, 2, 4, 8, 16, 32):
                        nn = 16.0 / d
                        if nn <= rem_u + 1e-6 and nn <= room + 1e-6:
                            nu = nn
                            break
                    if nu <= 0.0:
                        nu = 0.5
                        if nu > room + 1e-6:
                            sim_bar_idx += 1
                            sim_bar_units = 0.0
                            if sim_bar_idx < len(bars_info):
                                measure_units_target = bars_info[sim_bar_idx][5]
                            continue
                    sim_tokens += 1
                    if snap and prev_snap == snap:
                        sim_repeat += 1
                    if snap:
                        prev_snap = snap
                    sim_bar_units += nu
                    rem_u -= nu
                ct = chunk_end
        return sim_tokens, sim_repeat

    def active_content_with_dy(t0: float, prev_dy: str | None) -> tuple[str, str | None]:
        nonlocal voice_reference_count, voice_preserved_count
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
        if chosen:
            pitch_of = lambda x: int(x.get("pitch", GUITAR_OPEN_MIDI[int(x["string"]) - 1] + int(x["fret"])))
            top_note = max(chosen, key=pitch_of)
            bass_note = min(chosen, key=pitch_of)
            picked: list[dict[str, Any]] = [top_note]
            if bass_note is not top_note:
                picked.append(bass_note)
            remain = [n for n in chosen if n not in picked]
            remain = sorted(remain, key=lambda x: (-int(x["velocity"]), -pitch_of(x)))
            if chord_first_simplify:
                remain_cap = 0
            else:
                remain_cap = max(0, int(accompaniment_limit) - (2 if bass_note is not top_note else 1))
            picked.extend(remain[:remain_cap])
            chosen = sorted(picked, key=lambda x: (x["string"], x["fret"]))
            voice_reference_count += 1
            voice_preserved_count += 1
        max_vel = max(int(n["velocity"]) for n in chosen)
        dy = _velocity_to_dy(max_vel)
        if len(chosen) == 1:
            cn = chosen[0]
            base = f"{cn['fret']}.{cn['string']}"
        else:
            chord = " ".join(f"{n['fret']}.{n['string']}" for n in chosen)
            base = f"({chord})"

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
    sorted_boundaries = build_onset_boundaries()
    if len(sorted_boundaries) < 2:
        # 한국어 주석: 경계가 비정상적으로 적으면 기존 start/end 분할로 복구.
        ATTACK_ONLY_RENDER = False
        sorted_boundaries = build_onset_boundaries()

    def _safe_median(values: list[float], fallback: float) -> float:
        if not values:
            return fallback
        arr = sorted(values)
        return float(arr[len(arr) // 2])

    def _bar_onset_metrics(bar_start: float, bar_end: float) -> tuple[int, float]:
        hits = sorted(
            {
                round(float(n["start"]), 6)
                for n in note_events
                if (bar_start - 1e-6) <= float(n["start"]) < (bar_end - 1e-6)
            }
        )
        if len(hits) < 2:
            return len(hits), max(0.08, float(bar_end - bar_start))
        ioi = [max(1e-4, hits[i + 1] - hits[i]) for i in range(len(hits) - 1)]
        return len(hits), _safe_median(ioi, max(0.08, float(bar_end - bar_start)))

    def _resolve_bar_base_den(bpm: float, bar_onset_count: int, median_ioi_sec: float, bar_duration_sec: float) -> int:
        if bpm < 76.0 and bar_onset_count <= 2 and median_ioi_sec >= max(0.20, bar_duration_sec * 0.32):
            return 4
        if bpm < 85.0 and bar_onset_count <= 4 and median_ioi_sec >= 0.14:
            return 8
        if bpm < 85.0 and bar_onset_count <= 5:
            return 8
        if 85.0 <= bpm <= 120.0:
            return 16
        if bar_onset_count <= 3 and median_ioi_sec >= 0.18:
            return 8
        return 16

    def _resolve_max_nodes_per_bar(base_den_local: int, bpm: float, onset_count: int) -> int:
        base_cap = 8 if base_den_local == 8 else (6 if base_den_local == 4 else 12)
        bpm_bias = 2 if bpm < 80.0 else (0 if bpm < 120.0 else -1)
        density_bias = 2 if onset_count <= 3 else (0 if onset_count <= 8 else -2)
        return max(4, base_cap + bpm_bias + density_bias)

    bar_render_profile: dict[int, dict[str, float]] = {}
    for idx_b, (bs, be, _n, _d, bpm_b, _mu) in enumerate(bars_info):
        onset_count_b, med_ioi_b = _bar_onset_metrics(float(bs), float(be))
        bar_duration_b = max(0.001, float(be) - float(bs))
        base_den_b = _resolve_bar_base_den(float(bpm_b), int(onset_count_b), float(med_ioi_b), bar_duration_b)
        max_nodes_b = _resolve_max_nodes_per_bar(base_den_b, float(bpm_b), int(onset_count_b))
        bar_render_profile[idx_b] = {
            "base_den": float(base_den_b),
            "max_nodes_per_bar": float(max_nodes_b),
            "bar_onset_count": float(onset_count_b),
            "median_ioi_sec": float(med_ioi_b),
        }

    bar_idx = 0
    bar_tokens: list[str] = []
    bar_snapshots: list[tuple[tuple[int, int], ...]] = []
    bar_units = 0.0
    emitted_token_count = 0
    emitted_32_count = 0
    emitted_rest_count = 0
    emitted_repeat_snapshot = 0
    last_emitted_snapshot: tuple[tuple[int, int], ...] | None = None
    meter_ok_count = 0
    meter_fail_count = 0
    bar_32_count = 0
    bar_token_count = 0
    bar_token_densities: list[int] = []
    bar_node_counts: list[int] = []
    bar_attack_counts: list[int] = []
    bar_duration_fragmentation_values: list[float] = []
    bar_overflow_count = 0
    bar_attack_cap_applied_count = 0
    voice_reference_count = 0
    voice_preserved_count = 0
    bar_32_cap_applied_count = 0

    def flush_bar() -> None:
        nonlocal bar_tokens, bar_snapshots, bar_units, bar_idx, printed_ts, printed_bpm, meter_ok_count, meter_fail_count
        nonlocal bar_32_count, bar_token_count, bar_token_densities, emitted_token_count, emitted_32_count
        nonlocal bar_32_cap_applied_count, bar_overflow_count, bar_attack_cap_applied_count
        if bar_idx >= len(bars_info):
            return
        bs, be, num, den, bpm, measure_units_target = bars_info[bar_idx]
        profile = bar_render_profile.get(bar_idx, {})
        target_base_den = int(profile.get("base_den", float(base_den)))
        max_nodes_per_bar = max(4, int(profile.get("max_nodes_per_bar", 12)))
        # 한국어 주석: 마디 길이가 초과되면 뒤쪽 토큰부터 정리해 박자 예산을 맞춘다.
        while bar_units > measure_units_target + 1e-6 and bar_tokens:
            removed = bar_tokens.pop()
            bar_units -= _token_duration_units(removed)
        while bar_units < measure_units_target - 1e-6:
            remaining = measure_units_target - bar_units
            if remaining >= 1.0 - 1e-6:
                bar_tokens.append("r")
                bar_snapshots.append(tuple())
                bar_units += 1.0
                bar_token_count += 1
            elif remaining >= 0.5 - 1e-6:
                if bar_token_count > 0 and (bar_32_count * 100.0 / max(1, bar_token_count)) > bar_32_ratio_limit_pct:
                    bar_tokens.append(":16 r")
                    bar_snapshots.append(tuple())
                    bar_units += 1.0
                else:
                    bar_tokens.append(":32 r")
                    bar_snapshots.append(tuple())
                    bar_units += 0.5
                    bar_32_count += 1
                bar_token_count += 1
            else:
                break
        before_count = len(bar_tokens)
        before_32 = sum(1 for tok in bar_tokens if _parse_token(tok)[0] == 32)
        optimized_tokens, optimized_snaps = _optimize_bar_tokens_for_readability(
            bar_tokens,
            bar_snapshots,
            float(measure_units_target),
        )
        bar_tokens = optimized_tokens
        bar_snapshots = optimized_snaps
        # 한국어 주석: 마디 cap 초과 시 약한 토큰부터 흡수해 밀도를 낮춘다.
        while len(bar_tokens) > max_nodes_per_bar and bar_tokens:
            bar_overflow_count += 1
            bar_attack_cap_applied_count += 1
            weak_idx = next(
                (
                    i
                    for i, tok in enumerate(bar_tokens)
                    if _is_weak_token_content(_parse_token(tok)[1]) and _parse_token(tok)[1] != "r"
                ),
                None,
            )
            if weak_idx is None:
                weak_idx = next((i for i, tok in enumerate(bar_tokens) if _parse_token(tok)[1] == "r"), None)
            if weak_idx is None:
                weak_idx = len(bar_tokens) - 1
            bar_tokens[weak_idx] = _format_token(_parse_token(bar_tokens[weak_idx])[0], "r")
            compacted_tokens, compacted_snaps = _optimize_bar_tokens_for_readability(
                bar_tokens,
                bar_snapshots,
                float(measure_units_target),
            )
            if len(compacted_tokens) >= len(bar_tokens):
                break
            bar_tokens = compacted_tokens
            bar_snapshots = compacted_snaps
        while sum(1 for tok in bar_tokens if _parse_token(tok)[0] == 32) > max(0, int(bar_32_max_count)):
            changed = False
            for idx in range(len(bar_tokens) - 1):
                d1, c1 = _parse_token(bar_tokens[idx])
                d2, c2 = _parse_token(bar_tokens[idx + 1])
                if d1 == 32 and d2 == 32:
                    merged = _merge_two_32(c1 if c1 == c2 else "r")
                    bar_tokens[idx : idx + 2] = [merged]
                    bar_snapshots[idx : idx + 2] = [bar_snapshots[idx]]
                    bar_32_cap_applied_count += 1
                    changed = True
                    break
            if not changed:
                weak_idx = next(
                    (i for i, tok in enumerate(bar_tokens) if _parse_token(tok)[0] == 32 and _is_weak_token_content(_parse_token(tok)[1])),
                    None,
                )
                if weak_idx is None:
                    weak_idx = next((i for i, tok in enumerate(bar_tokens) if _parse_token(tok)[0] == 32), None)
                if weak_idx is None:
                    break
                bar_tokens[weak_idx] = ":16 r"
                bar_32_cap_applied_count += 1
                changed = True
            if not changed:
                break
        bar_units = sum(_token_duration_units(tok) for tok in bar_tokens)
        if abs(float(bar_units) - float(measure_units_target)) > 1e-3:
            bar_tokens = optimized_tokens
            bar_snapshots = optimized_snaps
            bar_units = sum(_token_duration_units(tok) for tok in bar_tokens)
        after_count = len(bar_tokens)
        after_32 = sum(1 for tok in bar_tokens if _parse_token(tok)[0] == 32)
        emitted_token_count = max(0, emitted_token_count + (after_count - before_count))
        emitted_32_count = max(0, emitted_32_count + (after_32 - before_32))
        bar_token_count = after_count
        bar_32_count = after_32
        if abs(float(bar_units) - float(measure_units_target)) <= 1e-3:
            meter_ok_count += 1
        else:
            meter_fail_count += 1
        if not bar_tokens:
            bar_idx += 1
            return
        attack_count = sum(1 for tok in bar_tokens if _parse_token(tok)[1] != "r")
        bar_node_counts.append(len(bar_tokens))
        bar_attack_counts.append(attack_count)
        dens_kinds = {int(_parse_token(tok)[0]) for tok in bar_tokens}
        bar_duration_fragmentation_values.append(float(max(0, len(dens_kinds) - 1)))
        bar_token_densities.append(len(bar_tokens))
        compacted_bar: list[str] = []
        prev_den = target_base_den
        for idx_tok, tok in enumerate(bar_tokens):
            den_tok, content_tok = _parse_token(tok)
            if idx_tok == 0:
                compacted_bar.append(f":{target_base_den} {content_tok}")
                prev_den = target_base_den
                continue
            if den_tok == prev_den:
                compacted_bar.append(content_tok)
            else:
                compacted_bar.append(f":{den_tok} {content_tok}")
                prev_den = den_tok
        bar_tokens = compacted_bar
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
        bar_snapshots = []
        bar_units = 0.0
        bar_32_count = 0
        bar_token_count = 0
        bar_idx += 1

    # 동일 운지가 이어지는 구간을 병합한 뒤, 16분 단위로 그리디 분해해 토큰을 만든다.
    prev_dy_m: str | None = None
    raw_chunks: list[tuple[float, float, tuple[tuple[int, int], ...], str, str]] = []
    merged_rows: list[list[Any]] = []
    merged_repeat_pairs = 0
    for idx in range(len(sorted_boundaries) - 1):
        t0b = float(sorted_boundaries[idx])
        t1b = float(sorted_boundaries[idx + 1])
        if t1b <= t0b + eps:
            continue
        snap = _tab_snapshot_key(note_events, t0b, eps)
        full_tok, prev_dy_m = active_content_with_dy(t0b, prev_dy_m)
        base_tok = _strip_dy_from_alphatex_note_token(full_tok)
        raw_chunks.append((t0b, t1b, snap, full_tok, base_tok))

    merged_rows, merged_repeat_pairs = merge_redundant_sustain_segments(raw_chunks)

    first_note_in_row: list[bool] = [True]

    def emit_units_slice(
        total_units: float,
        first_full: str,
        base_only: str,
        snapshot: tuple[tuple[int, int], ...],
    ) -> None:
        nonlocal bar_idx, bar_tokens, bar_units
        nonlocal emitted_token_count, emitted_32_count, emitted_repeat_snapshot, last_emitted_snapshot, emitted_rest_count
        nonlocal bar_32_count, bar_token_count
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
            den_found: int | None = None
            nu = 0.0
            base_den_cur = int(bar_render_profile.get(bar_idx, {}).get("base_den", float(base_den)))
            den_order = (1, 2, 4, 8, 16, 32)
            if base_den_cur == 8:
                den_order = (1, 2, 4, 8, 16, 32)
            elif base_den_cur == 4:
                den_order = (1, 2, 4, 8, 16, 32)
            for d in den_order:
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
            global_32_ratio = (emitted_32_count * 100.0 / max(1, emitted_token_count)) if emitted_token_count else 0.0
            bar_32_ratio = (bar_32_count * 100.0 / max(1, bar_token_count)) if bar_token_count else 0.0
            if den_found == 32 and (global_32_ratio >= duration_32_ratio_target_pct or bar_32_ratio >= bar_32_ratio_limit_pct):
                if rem_u >= 1.0 - 1e-6 and room >= 1.0 - 1e-6:
                    den_found = 16
                    nu = 1.0
            piece = first_full if first_note_in_row[0] else base_only
            first_note_in_row[0] = False
            tok = f":{den_found} {piece}" if den_found != base_den_cur else piece
            bar_tokens.append(tok)
            bar_snapshots.append(snapshot)
            emitted_token_count += 1
            bar_token_count += 1
            if den_found == 32:
                emitted_32_count += 1
                bar_32_count += 1
            if _parse_token(tok)[1] == "r":
                emitted_rest_count += 1
            if snapshot and last_emitted_snapshot == snapshot:
                emitted_repeat_snapshot += 1
            if snapshot:
                last_emitted_snapshot = snapshot
            bar_units += nu
            rem_u -= nu

    for row in merged_rows:
        st, en, snap, first_full, base_only = row[0], row[1], row[2], row[3], row[4]
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
            emit_units_slice(units_chunk, first_full, base_only, snap)
            ct = chunk_end

    if bar_tokens:
        flush_bar()
    while bar_idx < len(bars_info):
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

    # \\lyrics 는 \\staff 직후. 그 다음 \\chord 정의(곡에 등장하는 코드) → capo → 박자/튜닝/템포.
    header_core = (
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
    header = header_core

    tex = header + body + sync_block

    attempt = 0
    last_diag: dict[str, Any] | None = None
    while attempt < 2:
        diag = _validate_alphatex_with_alphatab(tex)
        last_diag = diag
        token_ok = bool(diag.get("tokenGuard", {}).get("ok", True))
        has_errors = bool(diag.get("hasErrors", False))
        if token_ok and not has_errors:
            if render_stats_out is not None:
                legacy_boundaries: set[float] = {0.0, last_bar_end}
                for n in analysis_note_events:
                    legacy_boundaries.add(float(n["start"]))
                    legacy_boundaries.add(float(n["end"]))
                for bs_l, be_l, *_ in bars_info:
                    legacy_boundaries.add(float(bs_l))
                    legacy_boundaries.add(float(be_l))
                legacy_chunks = _build_chunks_from_boundaries(uniq_sorted(list(legacy_boundaries)))
                legacy_rows, _legacy_merged_pairs = merge_redundant_sustain_segments(legacy_chunks)
                before_tokens_raw, _before_repeats_raw = _estimate_counts_for_rows(legacy_rows)
                before_tokens = max(1, int(before_tokens_raw))
                r_ratio_after = (float(emitted_rest_count) * 100.0 / max(1.0, float(emitted_token_count)))
                bar_density_p95_val = int(
                    np.percentile(np.asarray(bar_token_densities, dtype=np.float64), 95)
                ) if bar_token_densities else 0
                bar_node_p95_val = int(
                    np.percentile(np.asarray(bar_node_counts, dtype=np.float64), 95)
                ) if bar_node_counts else 0
                bar_attack_p95_val = int(
                    np.percentile(np.asarray(bar_attack_counts, dtype=np.float64), 95)
                ) if bar_attack_counts else 0
                duration_fragmentation_score = float(
                    np.mean(np.asarray(bar_duration_fragmentation_values, dtype=np.float64))
                ) if bar_duration_fragmentation_values else 0.0
                phrase_continuity_score = round(
                    1.0 - min(1.0, (float(emitted_repeat_snapshot) / max(1.0, float(emitted_token_count))) * 0.45),
                    4,
                )
                render_stats_out.clear()
                _stats_payload: dict[str, Any] = {
                        "render_strategy": "tempo_density_compact_with_meter_guard",
                        "render_event_mode": "hybrid_attack_adaptive_hold",
                        "attack_only_render": bool(ATTACK_ONLY_RENDER),
                        "meter_integrity": {"success": int(meter_ok_count), "fail": int(meter_fail_count)},
                        "token_counts": {
                            "before": int(before_tokens),
                            "after": int(emitted_token_count),
                            "reduction_rate_pct": round((before_tokens - emitted_token_count) * 100.0 / before_tokens, 2),
                        },
                        "duration_32_ratio_after_pct": round(
                            (emitted_32_count * 100.0 / max(1, emitted_token_count)), 2
                        ),
                        "duration_32_ratio_target": float(duration_32_ratio_target_pct),
                        "duration_32_ratio_met": bool(
                            (emitted_32_count * 100.0 / max(1, emitted_token_count))
                            <= duration_32_ratio_target_pct
                        ),
                        "bar_density_p95": int(bar_density_p95_val),
                        "bar_node_count_p95": int(bar_node_p95_val),
                        "bar_attack_p95": int(bar_attack_p95_val),
                        "r_gap_ratio_after_pct": round(float(r_ratio_after), 2),
                        "duration_fragmentation_score": round(float(duration_fragmentation_score), 4),
                        "phrase_continuity_score": float(phrase_continuity_score),
                        "penalty_fret_jump_p95": round(
                            max(0.0, float(np.percentile(np.asarray(play_jump_values, dtype=np.float64), 95)) - 7.0) * 0.08,
                            6,
                        )
                        if play_jump_values
                        else 0.0,
                        "penalty_string_cross_rate": round(
                            (float(play_string_cross) / max(1.0, float(play_total_pairs))) * 0.6,
                            6,
                        ),
                        "penalty_attack_burst": round(
                            max(
                                0.0,
                                float(
                                    (
                                        np.percentile(np.asarray(bar_token_densities, dtype=np.float64), 95)
                                        if bar_token_densities
                                        else 0.0
                                    )
                                    - float(bar_attack_max_count)
                                ),
                            )
                            * 0.09,
                            6,
                        ),
                        "voice_preservation_score": round(
                            float(voice_preserved_count) / max(1.0, float(voice_reference_count)),
                            4,
                        ),
                        "bar_32_cap_applied_count": int(bar_32_cap_applied_count),
                        "bar_attack_cap_applied_count": int(bar_attack_cap_applied_count),
                        "penalty_bar_overflow": round(float(bar_overflow_count) * 0.08, 6),
                        "penalty_duration_fragmentation": round(max(0.0, float(duration_fragmentation_score) - 1.0) * 0.26, 6),
                        "bar_attack_max_count": int(bar_attack_max_count),
                        "voice_hold_profile": voice_hold_profile,
                        "repeat_snapshot_counts": {
                            # 한국어 주석: 동일 snapshot 인접 세그먼트는 merge 단계에서 제거율을 산정.
                            "before": int(merged_repeat_pairs),
                            "after": 0,
                            "reduction_rate_pct": 100.0 if merged_repeat_pairs > 0 else 0.0,
                            "merged_pairs": int(merged_repeat_pairs),
                        },
                        "validator_passed": True,
                }
                render_stats_out.update(_stats_payload)
            if tab_output_dir is not None and note_events:
                try:
                    write_tab_compare_artifacts(
                        midi_path, analysis_note_events, tab_output_dir, refine=False
                    )
                except OSError:
                    pass
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
    if render_stats_out is not None:
        render_stats_out["validator_passed"] = False
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
) -> dict[str, Any]:
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    tempo_segments = _parse_tempo_segments(midi)
    ts_segments = _parse_time_signature_segments(midi)
    tempo = float(tempo_override) if tempo_override is not None else float(tempo_segments[0][1])
    tempo = max(20.0, min(300.0, tempo))
    ts0 = ts_segments[0]
    num, den = int(ts0[1]), int(ts0[2])

    beats, _grid_step_sec = _quantized_beats_from_midi(midi, tempo)

    raw_notes = _raw_guitar_notes_from_midi(midi)
    max_end = max((n["end"] for n in raw_notes), default=0.0)
    max_end = max(max_end, 0.01)
    bars_info = _compute_bars_info(midi, max_end, bpm_override=tempo_override)
    chord_labels = _bar_chord_labels(raw_notes, bars_info, int(capo))

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
    timed_lyrics: list[dict[str, Any]] = []
    lyrics_timing_source: str = "none"

    base_name = _safe_job_name_from_title(title, url)
    job_dir = _allocate_job_dir(Path("data") / "jobs", base_name)
    (job_dir / "audio").mkdir(parents=True, exist_ok=True)

    report(5, "download", "yt-dlp로 mp3 다운로드 시작")
    mp3_path = _download_mp3(url, job_dir / "audio")
    audio_dur = _probe_audio_duration_sec(mp3_path)
    lyrics, lyrics_source, timed_lyrics, lyrics_timing_source = _resolve_youtube_lyrics(
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
    timed_lyrics, lyrics_filter_stats = _filter_timed_lyrics_noise(timed_lyrics)
    if lyrics and lyrics.strip():
        report(10, "lyrics", f"가사 수집 완료 ({lyrics_source})")
    else:
        report(10, "lyrics", "가사 없음 (LRCLIB·설명에서 찾지 못함)")

    capo_guess = _guess_capo_from_text(title, lyrics)

    report(25, "separate", "Demucs로 stem 분리 시작")
    stems = _separate_demucs(mp3_path, job_dir / "stems")
    guitar_audio = _ensure_flat_guitar_stem_mp3(stems, job_dir / "stems")

    report(45, "basic-pitch", "Basic Pitch로 MIDI 변환 시작")
    midi_path = _basic_pitch_to_midi(guitar_audio, job_dir / "midi" / "guitar.mid")
    original_midi_bytes = midi_path.read_bytes()
    midi_pm_bpm = pretty_midi.PrettyMIDI(str(midi_path))
    _ts_bpm = _parse_tempo_segments(midi_pm_bpm)
    midi_bpm_meta = max(20.0, min(300.0, float(_ts_bpm[0][1]))) if _ts_bpm else 120.0
    (job_dir / "tab").mkdir(parents=True, exist_ok=True)
    candidate_root = job_dir / "tab" / "_candidates"
    candidate_root.mkdir(parents=True, exist_ok=True)
    midi_cleanup_stats: dict[str, Any] = {
        "enabled": MIDI_CLEANUP_ENABLED,
        "raw_midi_note_count": 0,
        "cleaned_midi_note_count": 0,
        "removed_short_note_count": 0,
        "merged_duplicate_note_count": 0,
    }
    midi_cleanup_warning: str | None = None

    snap_stats: dict[str, Any] = {"snapped_note_count": 0}
    snap_warning: str | None = None
    # MIDI_SNAP_ENABLED 시 오디오 박 대신 MIDI 템포+0초 앵커만 쓰려면 snap 헬퍼를 확장하면 된다.
    report(70, "alphatex", "MIDI/AlphaTex 반복 재튜닝 시작")
    retune_profiles: list[dict[str, Any]] = [
        {
            "iter": 1,
            "cleanup_strength": 1,
            "min_duration_sec": MIDI_CLEANUP_MIN_DURATION_SEC,
            "dup_tol": MIDI_CLEANUP_DUPLICATE_START_TOLERANCE_SEC,
            "velocity_ratio": MIDI_CLEANUP_VELOCITY_RELATIVE_RATIO,
            "duration32_target": 25.0,
            "bar32_limit": BAR_32_RATIO_LIMIT_PCT,
            "bar_32_max_count": 4,
            "bar_attack_max_count": 10,
            "chord_first_simplify": CHORD_FIRST_SIMPLIFY,
            "accompaniment_limit": 2,
            "melody_ioi_floor_sec": 0.055,
            "accompaniment_ioi_floor_sec": 0.105,
        },
        {
            "iter": 2,
            "cleanup_strength": 2,
            "min_duration_sec": max(MIDI_CLEANUP_MIN_DURATION_SEC, 0.10),
            "dup_tol": max(MIDI_CLEANUP_DUPLICATE_START_TOLERANCE_SEC, 0.09),
            "velocity_ratio": max(MIDI_CLEANUP_VELOCITY_RELATIVE_RATIO, 0.47),
            "duration32_target": 25.0,
            "bar32_limit": 25.0,
            "bar_32_max_count": 3,
            "bar_attack_max_count": 8,
            "chord_first_simplify": CHORD_FIRST_SIMPLIFY,
            "accompaniment_limit": 2,
            "melody_ioi_floor_sec": 0.065,
            "accompaniment_ioi_floor_sec": 0.125,
        },
        {
            "iter": 3,
            "cleanup_strength": 3,
            "min_duration_sec": max(MIDI_CLEANUP_MIN_DURATION_SEC, 0.12),
            "dup_tol": max(MIDI_CLEANUP_DUPLICATE_START_TOLERANCE_SEC, 0.11),
            "velocity_ratio": max(MIDI_CLEANUP_VELOCITY_RELATIVE_RATIO, 0.54),
            "duration32_target": 22.0,
            "bar32_limit": 22.0,
            "bar_32_max_count": 2,
            "bar_attack_max_count": 7,
            "chord_first_simplify": True,
            "accompaniment_limit": 1,
            "melody_ioi_floor_sec": 0.075,
            "accompaniment_ioi_floor_sec": 0.145,
        },
    ]
    candidate_runs: list[dict[str, Any]] = []
    selected_candidate: dict[str, Any] | None = None
    for profile in retune_profiles:
        iter_idx = int(profile["iter"])
        midi_path.write_bytes(original_midi_bytes)
        iter_snap_stats: dict[str, Any] = {"snapped_note_count": 0}
        try:
            midi_adjust = pretty_midi.PrettyMIDI(str(midi_path))
            cleanup_stats = _cleanup_transcribed_midi(
                midi_adjust,
                min_duration_sec=float(profile["min_duration_sec"]),
                duplicate_start_tolerance_sec=float(profile["dup_tol"]),
                velocity_relative_ratio=float(profile["velocity_ratio"]),
                cleanup_strength=int(profile["cleanup_strength"]),
            )
            midi_adjust.write(str(midi_path))
        except Exception as exc:
            cleanup_stats = dict(midi_cleanup_stats)
            cleanup_stats["iter_error"] = f"cleanup:{exc}"
            midi_cleanup_warning = f"midi_cleanup_skipped:{exc}"

        candidate_tab_dir = candidate_root / f"iter_{iter_idx}"
        candidate_tab_dir.mkdir(parents=True, exist_ok=True)
        render_stats_iter: dict[str, Any] = {}
        try:
            alphatex_iter = _midi_to_alphatex(
                midi_path,
                title=score_title,
                artist=display_artist,
                lyrics=lyrics,
                audio_duration_sec=audio_dur,
                capo=capo_guess,
                tempo_override=None,
                tab_output_dir=candidate_tab_dir,
                render_stats_out=render_stats_iter,
                duration_32_ratio_target_pct=float(profile["duration32_target"]),
                bar_32_ratio_limit_pct=float(profile["bar32_limit"]),
                bar_32_max_count=int(profile["bar_32_max_count"]),
                bar_attack_max_count=int(profile["bar_attack_max_count"]),
                chord_first_simplify=bool(profile["chord_first_simplify"]),
                accompaniment_limit=int(profile["accompaniment_limit"]),
                melody_ioi_floor_sec=float(profile["melody_ioi_floor_sec"]),
                accompaniment_ioi_floor_sec=float(profile["accompaniment_ioi_floor_sec"]),
            )
        except Exception as exc:
            render_stats_iter = {"validator_passed": False, "iter_error": f"alphatex:{exc}"}
            alphatex_iter = ":16 r |"
        compare_f1 = _read_compare_f1(candidate_tab_dir / "compare_report.json")
        cleaned = float(cleanup_stats.get("cleaned_midi_note_count", 0.0))
        raw = max(1.0, float(cleanup_stats.get("raw_midi_note_count", 0.0)))
        cleaned_ratio = cleaned / raw
        token_reduction = float(render_stats_iter.get("token_counts", {}).get("reduction_rate_pct", 0.0))
        duration32 = float(render_stats_iter.get("duration_32_ratio_after_pct", 100.0))
        bar_node_count_p95 = int(render_stats_iter.get("bar_node_count_p95", 999))
        duration_fragmentation_score = float(render_stats_iter.get("duration_fragmentation_score", 999.0))
        meter_fail = int(render_stats_iter.get("meter_integrity", {}).get("fail", 1))
        validator_passed = bool(render_stats_iter.get("validator_passed", False))
        kpi_met = (
            cleaned_ratio <= 0.85
            and duration32 <= 25.0
            and token_reduction >= 35.0
            and int(render_stats_iter.get("bar_density_p95", 999)) <= 12
            and bar_node_count_p95 <= 12
            and duration_fragmentation_score <= 1.8
            and meter_fail == 0
            and validator_passed
        )
        score_components = _score_candidate_components(render_stats_iter, cleaned_ratio, compare_f1)
        candidate_score = float(score_components.get("total_score", 1e9))
        candidate_runs.append(
            {
                "iter": iter_idx,
                "profile": profile,
                "cleanup_stats": cleanup_stats,
                "snap_stats": iter_snap_stats,
                "render_stats": render_stats_iter,
                "alphatex": alphatex_iter,
                "compare_f1_onset_symmetric": compare_f1,
                "cleaned_ratio": round(cleaned_ratio, 4),
                "token_reduction_rate_pct": round(token_reduction, 2),
                "duration_32_ratio_after_pct": round(duration32, 2),
                "meter_fail": meter_fail,
                "validator_passed": validator_passed,
                "kpi_met": kpi_met,
                "score": candidate_score,
                "score_components": score_components,
                "bar_density_p95": int(render_stats_iter.get("bar_density_p95", 999)),
                "bar_node_count_p95": int(bar_node_count_p95),
                "duration_fragmentation_score": round(duration_fragmentation_score, 4),
                "candidate_tab_dir": str(candidate_tab_dir),
                "midi_bytes": midi_path.read_bytes(),
            }
        )
        report(
            71 + iter_idx,
            "retune",
            (
                f"iter-{iter_idx}: cleaned/raw={cleaned_ratio:.3f}, token={token_reduction:.1f}%, "
                f":32={duration32:.1f}%, node_p95={bar_node_count_p95}, frag={duration_fragmentation_score:.2f}, meter_fail={meter_fail}, f1={compare_f1:.3f}"
            ),
        )
        must_iter3 = (
            int(render_stats_iter.get("bar_density_p95", 0)) > 13
            or float(render_stats_iter.get("token_counts", {}).get("after", 0.0)) > 1100.0
        )
        if kpi_met and iter_idx >= 2 and not must_iter3:
            selected_candidate = candidate_runs[-1]
            break
        if iter_idx < 2:
            continue
        if iter_idx == 2 and must_iter3:
            continue

    similarity_guard_rejected_iters = 0
    if selected_candidate is None and candidate_runs:
        baseline_f1 = float(candidate_runs[0].get("compare_f1_onset_symmetric", 0.0))
        eligible = [
            c
            for c in candidate_runs
            if (baseline_f1 - float(c.get("compare_f1_onset_symmetric", 0.0))) <= 0.03
        ]
        similarity_guard_rejected_iters = max(0, len(candidate_runs) - len(eligible))
        pool = eligible if eligible else candidate_runs
        selected_candidate = min(
            pool,
            key=lambda x: (
                float(x.get("score", 1e9)),
                float(x.get("render_stats", {}).get("token_counts", {}).get("after", 1e9)),
                float(x.get("bar_density_p95", 1e9)),
                float(x.get("duration_fragmentation_score", 1e9)),
                float(x.get("score_components", {}).get("playability_penalty_sum", 1e9)),
            ),
        )
    if selected_candidate is None:
        raise RuntimeError("재튜닝 후보를 생성하지 못했습니다.")

    midi_path.write_bytes(selected_candidate["midi_bytes"])
    midi_cleanup_stats = dict(selected_candidate["cleanup_stats"])
    snap_stats = dict(selected_candidate["snap_stats"])
    render_stats = dict(selected_candidate["render_stats"])
    alphatex = str(selected_candidate["alphatex"])
    fallback_applied = len(candidate_runs) > 1
    selected_iter = int(selected_candidate["iter"])
    kpi_unmet_reasons: list[str] = []
    if not bool(selected_candidate.get("kpi_met", False)):
        if float(selected_candidate.get("cleaned_ratio", 1.0)) > 0.85:
            kpi_unmet_reasons.append("cleaned/raw 비율 미달")
        if float(selected_candidate.get("duration_32_ratio_after_pct", 100.0)) > 25.0:
            kpi_unmet_reasons.append(":32 비율 미달")
        if float(selected_candidate.get("token_reduction_rate_pct", 0.0)) < 35.0:
            kpi_unmet_reasons.append("토큰 감소율 미달")
        if float(selected_candidate.get("bar_density_p95", 999.0)) > 12.0:
            kpi_unmet_reasons.append("bar_density_p95 미달")
        if float(selected_candidate.get("bar_node_count_p95", 999.0)) > 12.0:
            kpi_unmet_reasons.append("bar_node_count_p95 미달")
        if float(selected_candidate.get("duration_fragmentation_score", 999.0)) > 1.8:
            kpi_unmet_reasons.append("duration_fragmentation_score 미달")
        if int(selected_candidate.get("meter_fail", 1)) != 0:
            kpi_unmet_reasons.append("meter fail 존재")
        if not bool(selected_candidate.get("validator_passed", False)):
            kpi_unmet_reasons.append("validator 실패")

    selected_dir = Path(str(selected_candidate["candidate_tab_dir"]))
    try:
        for src_name, dest_name in (("compare_report.json", "compare_report.json"), ("tab_from_tab.mid", "tab_from_tab.mid")):
            src = selected_dir / src_name
            dest = job_dir / "tab" / dest_name
            if src.exists():
                shutil.copy2(src, dest)
    except OSError:
        pass

    score = _midi_to_score(
        midi_path,
        title=score_title,
        artist=display_artist,
        lyrics=lyrics,
        capo=capo_guess,
        tempo_override=None,
    )
    (job_dir / "tab").mkdir(parents=True, exist_ok=True)
    midi_for_lyrics = pretty_midi.PrettyMIDI(str(midi_path))
    note_attack_times = sorted(
        {
            round(float(note.start), 3)
            for inst in midi_for_lyrics.instruments
            if not inst.is_drum
            for note in inst.notes
            if note.end > note.start
        }
    )
    beat_anchors = sorted(set([0.0] + [float(t) for t in note_attack_times]))
    aligned_timed_lyrics, lyrics_alignment_offset_sec, lyrics_alignment_score, lyrics_alignment_mode, lyrics_alignment_segments = _align_timed_lyrics_to_timeline(
        timed_lyrics,
        beat_anchors,
        use_piecewise=True,
    )
    lyrics_timed_coverage_ratio = 0.0
    if timed_lyrics:
        lyrics_timed_coverage_ratio = float(len(aligned_timed_lyrics)) / max(1.0, float(len(timed_lyrics)))
    elif aligned_timed_lyrics:
        lyrics_timed_coverage_ratio = 1.0
    if not lyrics and aligned_timed_lyrics:
        lyrics = _timed_lyrics_to_plain(aligned_timed_lyrics)
        if lyrics:
            lyrics_source = "timed_lyrics_fallback"
    if aligned_timed_lyrics:
        (job_dir / "tab" / "lyrics_timed.json").write_text(
            json.dumps(
                {
                    "source": lyrics_timing_source,
                    "alignment_offset_sec": lyrics_alignment_offset_sec,
                    "alignment_score": lyrics_alignment_score,
                    "timed_coverage_ratio": lyrics_timed_coverage_ratio,
                    "alignment_mode": lyrics_alignment_mode,
                    "alignment_segments": lyrics_alignment_segments,
                    "line_count": len(aligned_timed_lyrics),
                    "items": aligned_timed_lyrics,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if isinstance(score.get("meta"), dict):
        score["meta"]["timedLyrics"] = [
            {
                "startSec": float(it.get("start_sec", 0.0)),
                "endSec": float(it.get("end_sec", 0.0)),
                "text": str(it.get("text", "")),
            }
            for it in aligned_timed_lyrics
            if str(it.get("text", "")).strip()
        ]
        score["meta"]["lyricsAlignmentScore"] = float(lyrics_alignment_score)
        score["meta"]["lyricsTimingSource"] = lyrics_timing_source
    interleaved_meta: dict[str, Any] = {}
    try:
        alphatex, interleaved_meta = _apply_interleaved_lyrics_to_alphatex(
            alphatex,
            midi_path,
            None,
            aligned_timed_lyrics,
            plain_lyrics_for_staff=(
                lyrics.strip() if lyrics and str(lyrics).strip() else None
            ),
        )
    except Exception as exc:
        interleaved_meta = {
            "applied": False,
            "error": str(exc),
            "skipped_reason": f"exception:{type(exc).__name__}",
        }
    lyrics_layout_for_files: str | None = (
        "interleaved_comment"
        if interleaved_meta.get("applied")
        else ("header_lyrics" if (lyrics and lyrics.strip() and "\\lyrics" in alphatex) else "none")
    )
    (job_dir / "tab" / "guitar.alphatex").write_text(alphatex, encoding="utf-8")
    (job_dir / "tab" / "score.json").write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
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
        "midi_bpm": float(midi_bpm_meta),
        "tempo_source": "midi_file",
    }
    if midi_cleanup_warning:
        job_meta_payload["midi_cleanup_warning"] = midi_cleanup_warning
    if snap_warning:
        job_meta_payload["midi_snap_warning"] = snap_warning
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
        lyrics_layout=lyrics_layout_for_files,
    )
    midi_chk = pretty_midi.PrettyMIDI(str(midi_path))
    (job_dir / "tab" / "summary.json").write_text(
        json.dumps(
            {
                "url": url,
                "mp3_path": str(mp3_path),
                "audio_duration_sec": audio_dur,
                "capo_guess": capo_guess,
                "lyrics_source": lyrics_source,
                "lyrics_timing_source": lyrics_timing_source,
                "lyrics_alignment_offset_sec": lyrics_alignment_offset_sec,
                "lyrics_alignment_score": lyrics_alignment_score,
                "lyrics_alignment_mode": lyrics_alignment_mode,
                "lyrics_alignment_segments": lyrics_alignment_segments,
                "lyrics_timed_path": str(job_dir / "tab" / "lyrics_timed.json"),
                "lyrics_filtered_line_count": int(lyrics_filter_stats.get("after_line_count", 0)),
                "lyrics_noise_removed_count": int(lyrics_filter_stats.get("removed_line_count", 0)),
                "lyrics_quality_report": {
                    "before_line_count": int(lyrics_filter_stats.get("before_line_count", 0)),
                    "after_line_count": int(lyrics_filter_stats.get("after_line_count", 0)),
                    "noise_removed_count": int(lyrics_filter_stats.get("removed_line_count", 0)),
                    "alignment_score_after": float(lyrics_alignment_score),
                },
                "lyrics_files": lyrics_files_info,
                "midi_has_named_chord_track_hint": _midi_has_named_chord_track_hint(midi_chk),
                "midi_note_events_only": True,
                "chords_on_score": "마디별 {ch} + 헤더 \\\\chord 정의(알려진 코드 형태). Basic Pitch MIDI에는 코드 문자열이 없음.",
                "guitar_stem_mp3": str(job_dir / "stems" / "guitar.mp3"),
                "stems": {k: str(v) for k, v in stems.items()},
                "midi_path": str(midi_path),
                "alphatex_path": str(job_dir / "tab" / "guitar.alphatex"),
                "tab_from_tab_midi": str(job_dir / "tab" / "tab_from_tab.mid"),
                "tab_compare_report": str(job_dir / "tab" / "compare_report.json"),
                "job_meta_path": str(job_dir / "job_meta.json"),
                "midi_bpm": float(midi_bpm_meta),
                "tempo_source": "midi_file",
                "midi_cleanup_profile": {
                    "enabled": bool(midi_cleanup_stats.get("enabled", MIDI_CLEANUP_ENABLED)),
                    "min_duration_sec": float(
                        midi_cleanup_stats.get("min_duration_sec", MIDI_CLEANUP_MIN_DURATION_SEC)
                    ),
                    "duplicate_start_tolerance_sec": float(
                        midi_cleanup_stats.get(
                            "duplicate_start_tolerance_sec", MIDI_CLEANUP_DUPLICATE_START_TOLERANCE_SEC
                        )
                    ),
                    "velocity_floor": int(midi_cleanup_stats.get("velocity_floor", MIDI_CLEANUP_VELOCITY_FLOOR)),
                    "velocity_relative_ratio": float(
                        midi_cleanup_stats.get("velocity_relative_ratio", MIDI_CLEANUP_VELOCITY_RELATIVE_RATIO)
                    ),
                },
                "raw_midi_note_count": int(midi_cleanup_stats.get("raw_midi_note_count", 0)),
                "cleaned_midi_note_count": int(midi_cleanup_stats.get("cleaned_midi_note_count", 0)),
                "removed_short_note_count": int(midi_cleanup_stats.get("removed_short_note_count", 0)),
                "merged_duplicate_note_count": int(midi_cleanup_stats.get("merged_duplicate_note_count", 0)),
                "midi_reduction_rate_pct": round(
                    100.0
                    * (
                        1.0
                        - (
                            float(midi_cleanup_stats.get("cleaned_midi_note_count", 0))
                            / max(1.0, float(midi_cleanup_stats.get("raw_midi_note_count", 0)))
                        )
                    ),
                    2,
                ),
                "snap_profile": {
                    "enabled": MIDI_SNAP_ENABLED,
                    "max_snap_error_sec": MIDI_SNAP_MAX_ERROR_SEC,
                    "snap_note_end": MIDI_SNAP_NOTE_END,
                },
                "snapped_note_count": int(snap_stats.get("snapped_note_count", 0)),
                "duration_32_ratio_target": float(render_stats.get("duration_32_ratio_target", DURATION_32_RATIO_TARGET_PCT)),
                "duration_32_ratio_met": bool(render_stats.get("duration_32_ratio_met", False)),
                "bar_density_p95": int(render_stats.get("bar_density_p95", 0)),
                "bar_node_count_p95": int(render_stats.get("bar_node_count_p95", 0)),
                "bar_attack_p95": int(render_stats.get("bar_attack_p95", 0)),
                "duration_fragmentation_score": float(render_stats.get("duration_fragmentation_score", 0.0)),
                "r_gap_ratio_after_pct": float(render_stats.get("r_gap_ratio_after_pct", 0.0)),
                "phrase_continuity_score": float(render_stats.get("phrase_continuity_score", 0.0)),
                "bar_32_cap_applied_count": int(render_stats.get("bar_32_cap_applied_count", 0)),
                "bar_attack_cap_applied_count": int(render_stats.get("bar_attack_cap_applied_count", 0)),
                "voice_preservation_score": float(render_stats.get("voice_preservation_score", 0.0)),
                "lyrics_timed_coverage_ratio": float(lyrics_timed_coverage_ratio),
                "lyrics_layout": lyrics_layout_for_files,
                "lyrics_interleaved_applied": bool(interleaved_meta.get("applied", False)),
                "lyrics_staff_reinjected": bool(interleaved_meta.get("staff_lyrics_reinjected", False)),
                "lyrics_interleaved_error": interleaved_meta.get("error"),
                "lyrics_interleaved_skipped_reason": interleaved_meta.get("skipped_reason"),
                "lyrics_interleaved_char_count": int(interleaved_meta.get("interleaved_char_count", 0)),
                "lyrics_interleaved_validator_ok": interleaved_meta.get("validator_ok_after"),
                "render_event_mode": str(render_stats.get("render_event_mode", "hybrid_attack_adaptive_hold")),
                "fixed_den": render_stats.get("fixed_den"),
                "slots_per_bar": render_stats.get("slots_per_bar"),
                "slots_per_bar_by_bar_head": render_stats.get("slots_per_bar_by_bar_head"),
                "voice_hold_profile": render_stats.get("voice_hold_profile", {}),
                "kpi_fallback_applied": bool(fallback_applied),
                "kpi_selected_iter": int(selected_iter),
                "kpi_retune_candidates": [
                    {
                        "iter": int(c.get("iter", 0)),
                        "cleaned_raw_ratio": float(c.get("cleaned_ratio", 1.0)),
                        "token_reduction_rate_pct": float(c.get("token_reduction_rate_pct", 0.0)),
                        "duration_32_ratio_after_pct": float(c.get("duration_32_ratio_after_pct", 100.0)),
                        "meter_fail": int(c.get("meter_fail", 1)),
                        "validator_passed": bool(c.get("validator_passed", False)),
                        "f1_onset_symmetric": float(c.get("compare_f1_onset_symmetric", 0.0)),
                        "bar_density_p95": float(c.get("bar_density_p95", 0.0)),
                        "bar_node_count_p95": float(c.get("bar_node_count_p95", 0.0)),
                        "duration_fragmentation_score": float(c.get("duration_fragmentation_score", 0.0)),
                        "voice_preservation_score": float(c.get("render_stats", {}).get("voice_preservation_score", 0.0)),
                        "phrase_continuity_score": float(c.get("render_stats", {}).get("phrase_continuity_score", 0.0)),
                        "bar_attack_p95": float(c.get("render_stats", {}).get("bar_attack_p95", 0.0)),
                        "r_gap_ratio_after_pct": float(c.get("render_stats", {}).get("r_gap_ratio_after_pct", 0.0)),
                        "lyrics_alignment_score": float(lyrics_alignment_score),
                        "lyrics_timed_coverage_ratio": float(lyrics_timed_coverage_ratio),
                        "lyrics_noise_removed_count": int(lyrics_filter_stats.get("removed_line_count", 0)),
                        "playability_penalty_sum": float(c.get("score_components", {}).get("playability_penalty_sum", 0.0)),
                        "score": float(c.get("score", -999.0)),
                        "score_components": c.get("score_components", {}),
                        "kpi_met": bool(c.get("kpi_met", False)),
                    }
                    for c in candidate_runs
                ],
                "fallback_candidate_scores": [
                    {
                        "iter": int(c.get("iter", 0)),
                        "score": float(c.get("score", 0.0)),
                        "score_components": c.get("score_components", {}),
                        "token_after": float(c.get("render_stats", {}).get("token_counts", {}).get("after", 0.0)),
                        "bar_density_p95": float(c.get("bar_density_p95", 0.0)),
                        "duration_fragmentation_score": float(c.get("duration_fragmentation_score", 0.0)),
                    }
                    for c in candidate_runs
                ],
                "selected_profile": {
                    "iter": int(selected_candidate.get("iter", 0)),
                    "score": float(selected_candidate.get("score", 0.0)),
                    "profile": selected_candidate.get("profile", {}),
                    "score_components": selected_candidate.get("score_components", {}),
                    "selection_reason": "min_score_then_token_after_then_bar_density_then_duration_fragmentation_then_playability_with_f1_guard",
                },
                "kpi_selected_score": float(selected_candidate.get("score", -999.0)),
                "similarity_guard_rejected_iters": int(similarity_guard_rejected_iters),
                "kpi_unmet_reasons": kpi_unmet_reasons,
                "tab_tuning_profile": {
                    "max_notes_per_slot": MAX_NOTES_PER_SLOT,
                    "onset_tolerance_sec": ONSET_TOLERANCE_SEC,
                    "merge_min_ioi_sec": MERGE_MIN_IOI_SEC,
                    "sustain_release_sec": SUSTAIN_RELEASE_SEC,
                    "max_sustain_beats": MAX_SUSTAIN_BEATS,
                    "grid_mode": "fixed_16th",
                    "fingering_jump_penalty": {
                        "string_move_coeff": 0.50,
                        "jump_threshold_fret": 10,
                        "jump_excess_coeff": 1.2,
                    },
                },
                "chord_inference_profile": {
                    "method": "midi_weighted_with_bass_key_ngram",
                    "extra_penalty": CHORD_EXTRA_PENALTY,
                    "min_score_ratio": CHORD_MIN_SCORE_RATIO,
                    "bass_prior_scale": CHORD_BASS_PRIOR_SCALE,
                    "key_context_bonus": CHORD_KEY_CONTEXT_BONUS,
                    "ngram_root_jump_penalty": CHORD_NGRAM_ROOT_JUMP_PENALTY,
                    "ngram_quality_switch_penalty": CHORD_NGRAM_QUALITY_SWITCH_PENALTY,
                    "short_note_ratio": CHORD_SHORT_NOTE_RATIO,
                    "short_note_weight": CHORD_SHORT_NOTE_WEIGHT,
                },
                # 한국어 주석: 새 렌더 전략/토큰 압축 통계를 summary 메타에 노출.
                "render_strategy": render_stats.get("render_strategy", "onset_centric_with_meter_guard"),
                "token_reduction_stats": render_stats,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report(100, "done", "4단계 파이프라인 완료")

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
