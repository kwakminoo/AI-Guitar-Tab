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

GUITAR_OPEN_MIDI = [64, 59, 55, 50, 45, 40]  # E4, B3, G3, D3, A2, E2
GUITAR_MIN_PITCH = 40
GUITAR_MAX_PITCH = 88
MIN_NOTE_VELOCITY = 18


def _escape_alpha_tex_string(value: str) -> str:
    # alphaTex string literal은 backslash/quote 이스케이프가 중요하다.
    cleaned = value.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    cleaned = cleaned.replace("\\", "\\\\").replace('"', '\\"')
    # 과도하게 긴 문자열은 파서/렌더 부하 및 진단 노이즈를 유발하므로 상한을 둔다.
    return cleaned[:200]


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


def _fetch_youtube_meta(url: str) -> tuple[str, str | None, str | None]:
    completed = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--dump-single-json", "--skip-download", "--no-warnings", url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return _safe_job_name(url), None, None
    try:
        data = json.loads(completed.stdout or "{}")
    except Exception:
        return _safe_job_name(url), None, None
    title = str(data.get("title") or _safe_job_name(url))
    artist = data.get("artist") or data.get("uploader") or data.get("channel")
    if artist is not None:
        artist = str(artist)
    description = str(data.get("description") or "").strip()
    lyrics = None
    if description:
        first_paragraph = description.split("\n\n", 1)[0].strip()
        if len(first_paragraph) > 0:
            lyrics = first_paragraph[:400]
    return title, artist, lyrics


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


def _midi_to_alphatex(midi_path: Path, title: str) -> str:
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    tempo = 120.0
    _times, tempi = midi.get_tempo_changes()
    if len(tempi) > 0:
        tempo = float(tempi[0])

    # title 문자열을 먼저 안전하게 이스케이프한다(lexer 오류 대부분이 여기서 발생한다).
    safe_title = _escape_alpha_tex_string(title)

    beats, _grid_step_sec = _quantized_beats_from_midi(midi, tempo)
    beats = sorted(beats, key=lambda b: float(b.get("time", 0.0)))

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
    quarter_sec = 60.0 / max(1.0, tempo)
    base_unit_sec = quarter_sec / 4.0  # 1/16
    measure_units_target = 16  # 4/4 in 1/16 grid
    measure_sec = measure_units_target * base_unit_sec

    def duration_seconds_to_den(duration_sec: float, base_unit_sec_: float) -> int:
        # alphaTex durationChange value는 분모(예: :4, :8, :16, :32)로 해석된다.
        units = duration_sec / max(1e-9, base_unit_sec_)
        # :16이 1/16, :8이 1/8(=2 units), :32가 1/32(=0.5 units) ...
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

    # alphaTex body는 “note interval 경계 + 마디 경계”에서 내용이 바뀌도록 만든다.
    max_end = max([n["end"] for n in note_events], default=0.0)
    last_bar_end = measure_sec if max_end <= eps else math.ceil(max_end / measure_sec) * measure_sec

    boundaries: set[float] = {0.0, last_bar_end}
    for n in note_events:
        boundaries.add(float(n["start"]))
        boundaries.add(float(n["end"]))

    t = 0.0
    while t <= last_bar_end + eps:
        boundaries.add(float(t))
        t += measure_sec

    def uniq_sorted(values: list[float]) -> list[float]:
        values_sorted = sorted(values)
        out: list[float] = []
        for v in values_sorted:
            if not out or abs(v - out[-1]) > 1e-5:
                out.append(round(v, 6))
        return out

    sorted_boundaries = uniq_sorted(list(boundaries))

    def active_content(t0: float) -> str:
        # t0에서 active인 note들만 모아 alphaTex token으로 만든다.
        active: list[dict[str, Any]] = [
            n for n in note_events if n["start"] <= t0 + eps and n["end"] > t0 + eps
        ]
        if not active:
            return "r"

        # 같은 string에서 겹치는 note는 더 강한 velocity + 낮은 프렛 우선으로 하나만 남긴다.
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
        if len(chosen) == 1:
            cn = chosen[0]
            return f"{cn['fret']}.{cn['string']}"

        chord = " ".join(f"{n['fret']}.{n['string']}" for n in chosen)
        return f"({chord})"

    bar_tokens: list[str] = []
    bar_units = 0.0
    bars: list[str] = []

    def push_bar() -> None:
        nonlocal bar_tokens, bar_units, bars
        # rounding 오차로 인해 bar_units가 남을 수 있으므로 rest로 마감한다.
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
        if bar_tokens:
            first = bar_tokens[0]
            if not first.lstrip().startswith(":"):
                bar_tokens[0] = f":{base_den} {first}"
            bars.append(f"{' '.join(bar_tokens)} |")
        bar_tokens = []
        bar_units = 0.0

    for idx in range(len(sorted_boundaries) - 1):
        t0 = float(sorted_boundaries[idx])
        t1 = float(sorted_boundaries[idx + 1])
        if t1 <= t0 + eps:
            continue

        duration_sec = max(0.0, t1 - t0)
        den_value = duration_seconds_to_den(duration_sec, base_unit_sec)
        seg_units = 16 / max(1, den_value)

        # bar 경계에서 강제 마감
        if bar_units + seg_units > measure_units_target + 1e-6 and bar_tokens:
            push_bar()

        content = active_content(t0)
        if den_value != base_den:
            beat_token = f":{den_value} {content}"
        else:
            beat_token = content

        bar_tokens.append(beat_token)
        bar_units += seg_units

    if bar_tokens:
        push_bar()

    body = "\n".join(bars) if bars else f":{base_den} r |"

    tex = (
        f"\\title \"{safe_title}\"\n"
        "\\artist \"\"\n"
        "\\track \"Guitar\" { instrument \"Acoustic Guitar Steel\" }\n"
        "\\staff {score tabs}\n"
        "\\ts (4 4)\n"
        "\\tuning (E4 B3 G3 D3 A2 E2)\n"
        f"\\tempo {int(round(tempo))}\n"
        + body
    )

    # alphaTex 진단: 오류가 있으면 UI 렌더 실패가 아니라 backend에서 차단한다.
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
            # title 문자열 이스케이프를 더 엄격하게 정리해 재시도한다.
            safe_title = _escape_alpha_tex_string(title)
            tex = (
                f"\\title \"{safe_title}\"\n"
                "\\artist \"\"\n"
                "\\track \"Guitar\" { instrument \"Acoustic Guitar Steel\" }\n"
                "\\staff {score tabs}\n"
                "\\ts (4 4)\n"
                "\\tuning (E4 B3 G3 D3 A2 E2)\n"
                f"\\tempo {int(round(tempo))}\n"
                + body
            )
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


def _midi_to_score(midi_path: Path, title: str) -> dict[str, Any]:
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    tempo = 120.0
    _times, tempi = midi.get_tempo_changes()
    if len(tempi) > 0:
        tempo = float(tempi[0])

    beats, _grid_step_sec = _quantized_beats_from_midi(midi, tempo)

    return {
        "version": 1,
        "meta": {
            "title": title,
            "tempo": int(round(tempo)),
            "timeSignature": {"numerator": 4, "denominator": 4},
            "key": "C major",
            "capo": 0,
            "chords": [],
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

    title, artist, lyrics = _fetch_youtube_meta(url)
    base_name = _safe_job_name_from_title(title, url)
    job_dir = _allocate_job_dir(Path("data") / "jobs", base_name)
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
    alphatex = _midi_to_alphatex(midi_path, title=title)
    score = _midi_to_score(midi_path, title=title)
    (job_dir / "tab").mkdir(parents=True, exist_ok=True)
    (job_dir / "tab" / "guitar.alphatex").write_text(alphatex, encoding="utf-8")
    (job_dir / "tab" / "score.json").write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
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

    return PipelineResult(
        job_dir=job_dir,
        mp3_path=mp3_path,
        stems=stems,
        midi_path=midi_path,
        alphatex=alphatex,
        score=score,
        title=title,
        artist=artist or "",
        lyrics=lyrics,
    )
