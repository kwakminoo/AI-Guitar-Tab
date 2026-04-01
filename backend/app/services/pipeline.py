from __future__ import annotations

import hashlib
import json
import os
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

from .beat_audio import analyze_beats_from_mix_mp3, snap_midi_notes_to_sixteenth_grid
from .lyrics_lrclib import fetch_lyrics_from_lrclib, parse_artist_and_track_from_youtube_title

GUITAR_OPEN_MIDI = [64, 59, 55, 50, 45, 40]  # E4, B3, G3, D3, A2, E2
GUITAR_MIN_PITCH = 40
GUITAR_MAX_PITCH = 88
MIN_NOTE_VELOCITY = 18

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
    if re.match(r"^https?://", first_paragraph.strip()):
        return None
    return first_paragraph[:800]


def _resolve_youtube_lyrics(
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
            stems[name] = matched[0]
    # guitar/piano가 없는 모델에서도 최소 stems 반환
    return stems


def _basic_pitch_to_midi(guitar_audio: Path, midi_out: Path) -> Path:
    midi_out.parent.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "basic_pitch.predict", str(midi_out.parent), str(guitar_audio)])
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


def _quantized_beats_from_midi(midi: pretty_midi.PrettyMIDI, tempo: float) -> tuple[list[dict[str, Any]], float]:
    """
    MIDI note start/end를 1/16 단위로 기본 양자화하고,
    필요할 경우 1/32 단위까지 적응적으로 사용한다.
    """

    quarter = 60.0 / max(1.0, tempo)
    step_16 = quarter / 4.0  # 1/16
    step_32 = step_16 / 2.0  # 1/32

    # 1/16 vs 1/32에서 start/end 스냅 오차를 비교해 그리드 선택
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

        # 같은 slot에서 중복 줄 제거 + 최대 4음 제한
        by_string: dict[int, dict[str, Any]] = {}
        for mn in mapped_notes:
            existing = by_string.get(mn["string"])
            if existing is None:
                by_string[mn["string"]] = mn
                continue
            if (mn["velocity"], -mn["fret"]) > (existing["velocity"], -existing["fret"]):
                by_string[mn["string"]] = mn

        normalized_notes = sorted(by_string.values(), key=lambda x: (x["string"], x["fret"]))[:4]
        beats.append(
            {
                "time": time_value,
                "chord": None,
                "lyric": None,
                "notes": normalized_notes,
            }
        )

        prev_lead_pos = best_lead_pos[k]

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
                }
            )

    base_den = 16

    def duration_seconds_to_den(duration_sec: float, base_unit_sec_: float) -> int:
        units = duration_sec / max(1e-9, base_unit_sec_)
        allowed = [32, 16, 8, 4, 2, 1]
        best_den = 16
        best_diff = float("inf")
        for cand_den in allowed:
            cand_units = 16 / cand_den
            diff = abs(cand_units - units)
            if diff < best_diff:
                best_diff = diff
                best_den = int(cand_den)
        return int(best_den)

    eps = 1e-6

    ts_pairs: list[tuple[float, tuple[int, int]]] = [(t, (n, d)) for t, n, d in ts_segments]
    raw_notes = _raw_guitar_notes_from_midi(midi)
    max_q = max([n["end"] for n in note_events], default=0.0)
    max_raw = max([n["end"] for n in raw_notes], default=0.0)
    max_end = max(max_q, max_raw, 0.01)

    # 가변 마디 길이(박자표·템포) 타임라인
    bars_info = _compute_bars_info(midi, max_end, bpm_override=tempo_override)
    bar_chords = _bar_chord_labels(raw_notes, bars_info, int(capo))

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

        if prev_dy is None or dy != prev_dy:
            return f"{base} {{dy {dy}}}", dy
        return base, prev_dy

    bars: list[str] = []
    prev_dy: str | None = None

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
    boundaries: set[float] = {0.0, last_bar_end}
    for n in note_events:
        boundaries.add(float(n["start"]))
        boundaries.add(float(n["end"]))
    for bs, be, *_r in bars_info:
        boundaries.add(bs)
        boundaries.add(be)
    sorted_boundaries = uniq_sorted(list(boundaries))

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

    for idx in range(len(sorted_boundaries) - 1):
        t0 = float(sorted_boundaries[idx])
        t1 = float(sorted_boundaries[idx + 1])
        if t1 <= t0 + eps:
            continue

        while bar_idx < len(bars_info) and t0 >= bars_info[bar_idx][1] - eps:
            if bar_tokens:
                flush_bar()
            else:
                bar_idx += 1

        if bar_idx >= len(bars_info):
            break

        bs, be, num, den, bpm, measure_units_target = bars_info[bar_idx]
        base_unit_sec = (60.0 / max(20.0, bpm)) / 4.0

        duration_sec = max(0.0, t1 - t0)
        den_value = duration_seconds_to_den(duration_sec, base_unit_sec)
        seg_units = 16 / max(1, den_value)

        if bar_units + seg_units > measure_units_target + 1e-6 and bar_tokens:
            flush_bar()
            if bar_idx >= len(bars_info):
                break
            bs, be, num, den, bpm, measure_units_target = bars_info[bar_idx]
            base_unit_sec = (60.0 / max(20.0, bpm)) / 4.0

        if bar_units + seg_units > measure_units_target + 1e-6:
            seg_units = max(0.0, measure_units_target - bar_units)
            if seg_units <= 1e-9:
                continue

        content, prev_dy = active_content_with_dy(t0, prev_dy)
        if den_value != base_den:
            beat_token = f":{den_value} {content}"
        else:
            beat_token = content

        bar_tokens.append(beat_token)
        bar_units += seg_units

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

    # \\lyrics 는 \\staff 직후에 두어 스태프 컨텍스트에서 가사가 박에 분배되도록 한다 (alphaTex 문서 권장 순서에 맞춤).
    header = (
        f"\\title \"{safe_title}\"\n"
        + (f"\\artist \"{safe_artist}\"\n" if safe_artist else "\\artist \"\"\n")
        + f'\\track "Guitar" {{ instrument "{inst_name}" }}\n'
        "\\staff {score tabs}\n"
        + lyrics_line
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
            return tex

        if attempt == 0 and _should_retry_after_alphatex_diagnostics(diag):
            safe_title = _escape_alpha_tex_string(title)
            header = (
                f"\\title \"{safe_title}\"\n"
                + (f"\\artist \"{safe_artist}\"\n" if safe_artist else "\\artist \"\"\n")
                + f'\\track "Guitar" {{ instrument "{inst_name}" }}\n'
                "\\staff {score tabs}\n"
                + lyrics_line
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

    base_name = _safe_job_name_from_title(title, url)
    job_dir = _allocate_job_dir(Path("data") / "jobs", base_name)
    (job_dir / "audio").mkdir(parents=True, exist_ok=True)

    report(5, "download", "yt-dlp로 mp3 다운로드 시작")
    mp3_path = _download_mp3(url, job_dir / "audio")
    audio_dur = _probe_audio_duration_sec(mp3_path)
    lyrics, lyrics_source = _resolve_youtube_lyrics(
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

    capo_guess = _guess_capo_from_text(title, lyrics)

    report(18, "beat", "풀 믹스에서 BPM·박 시각 추정(librosa)")
    beat_meta = analyze_beats_from_mix_mp3(mp3_path)
    detected_bpm: float | None = None
    beat_times_out: list[float] = []
    downbeat_indices_out: list[int] = []
    if beat_meta.get("ok") and beat_meta.get("bpm") is not None:
        detected_bpm = float(beat_meta["bpm"])
        beat_times_out = list(beat_meta.get("beat_times_sec") or [])
        downbeat_indices_out = list(beat_meta.get("downbeat_indices") or [])
        report(20, "beat", f"BPM≈{detected_bpm:.1f}, 박 {len(beat_times_out)}개")
    else:
        err = beat_meta.get("error") or "unknown"
        report(20, "beat", f"박 추정 실패·MIDI 템포 사용 ({err})")

    report(30, "separate", "Demucs로 stem 분리 시작")
    stems = _separate_demucs(mp3_path, job_dir / "stems")

    guitar_audio = stems.get("guitar") or stems.get("other")
    if not guitar_audio:
        raise RuntimeError("Demucs 출력에서 guitar/other stem을 찾지 못했습니다.")

    report(60, "basic-pitch", "Basic Pitch로 MIDI 변환 시작")
    midi_path = _basic_pitch_to_midi(guitar_audio, job_dir / "midi" / "guitar.mid")

    if detected_bpm is not None:
        try:
            midi_adjust = pretty_midi.PrettyMIDI(str(midi_path))
            snap_midi_notes_to_sixteenth_grid(midi_adjust, detected_bpm, beat_times_out)
            midi_adjust.write(str(midi_path))
        except Exception as exc:
            report(65, "beat", f"MIDI 스냅 실패(템포만 반영): {exc}")

    report(85, "alphatex", "MIDI를 AlphaTex 문법으로 변환 시작")
    alphatex = _midi_to_alphatex(
        midi_path,
        title=score_title,
        artist=display_artist,
        lyrics=lyrics,
        audio_duration_sec=audio_dur,
        capo=capo_guess,
        tempo_override=detected_bpm,
    )
    score = _midi_to_score(
        midi_path,
        title=score_title,
        artist=display_artist,
        lyrics=lyrics,
        capo=capo_guess,
        tempo_override=detected_bpm,
    )
    (job_dir / "tab").mkdir(parents=True, exist_ok=True)
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
        "bpm": detected_bpm,
        "beat_times_sec": beat_times_out if detected_bpm is not None else [],
        "downbeat_indices": downbeat_indices_out if detected_bpm is not None else [],
        "beat_analysis_ok": bool(beat_meta.get("ok")),
        "beat_analysis_raw": {k: v for k, v in beat_meta.items() if k != "error"},
    }
    if beat_meta.get("error"):
        job_meta_payload["beat_analysis_error"] = beat_meta["error"]
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
                "capo_guess": capo_guess,
                "lyrics_source": lyrics_source,
                "lyrics_files": lyrics_files_info,
                "midi_has_named_chord_track_hint": _midi_has_named_chord_track_hint(midi_chk),
                "midi_note_events_only": True,
                "chords_on_score": "마디별 음높이로 추정(표기용). Basic Pitch MIDI에는 코드 문자열이 들어가지 않음.",
                "stems": {k: str(v) for k, v in stems.items()},
                "midi_path": str(midi_path),
                "alphatex_path": str(job_dir / "tab" / "guitar.alphatex"),
                "job_meta_path": str(job_dir / "job_meta.json"),
                "audio_bpm": detected_bpm,
                "beat_times_count": len(beat_times_out) if detected_bpm is not None else 0,
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
