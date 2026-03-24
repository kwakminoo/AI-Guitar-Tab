from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional

import torch
import whisper


@dataclass(frozen=True)
class SeparationResult:
    vocals_path: Path
    guitar_path: Optional[Path]


@dataclass(frozen=True)
class LyricSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class LyricsResult:
    full_text: str
    segments: List[LyricSegment]
    model_name: str
    device: Literal["cpu", "cuda"]


def has_cuda() -> bool:
    return torch.cuda.is_available()


def separate_vocals_and_guitar(
    wav_path: Path,
    output_root: Optional[Path] = None,
    model_name: str = "htdemucs",
) -> SeparationResult:
    """
    Demucs CLI를 사용하여 오디오를 분리한다.

    기본적으로 voclas, bass, drums, other 4스템을 생성하며,
    기타 트랙은 other에 섞여 있을 수 있으므로 우선 vocals만 필수로 사용하고,
    guitar는 있으면 반환하는 형태로 둔다.
    """
    if not wav_path.exists():
        raise FileNotFoundError(f"입력 오디오 파일을 찾을 수 없습니다: {wav_path}")

    wav_path = wav_path.resolve()
    if output_root is None:
        output_root = wav_path.parent / "demucs_outputs"
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    # demucs CLI 호출
    # 예: python -m demucs -n htdemucs -o <output_root> <wav_path>
    cmd = [
        "python",
        "-m",
        "demucs",
        "-n",
        model_name,
        "-o",
        str(output_root),
        str(wav_path),
    ]

    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Demucs 실행 실패 (exit={completed.returncode}): {completed.stderr}"
        )

    # Demucs 출력 구조: <output_root>/<model_name>/<stem_dir>/*.wav
    # stem_dir 이름은 원본 파일명과 비슷하므로, 첫 번째 디렉터리를 사용
    model_dir = output_root / model_name
    if not model_dir.exists():
        raise RuntimeError(f"Demucs 출력 디렉터리를 찾을 수 없습니다: {model_dir}")

    stem_dirs = [d for d in model_dir.iterdir() if d.is_dir()]
    if not stem_dirs:
        raise RuntimeError(f"Demucs 출력 스템 디렉터리가 비어 있습니다: {model_dir}")

    stem_dir = stem_dirs[0]

    vocals_path = stem_dir / "vocals.wav"
    # Demucs 기본 모델은 'guitar.wav'가 아니라 stems만 제공하는 경우가 많음.
    # 프로젝트 구조상 기타 전용 모델을 나중에 붙일 수 있도록 Optional 처리.
    guitar_candidate = stem_dir / "guitar.wav"

    if not vocals_path.exists():
        raise RuntimeError(f"보컬 트랙(vocals.wav)을 찾을 수 없습니다: {vocals_path}")

    guitar_path = guitar_candidate if guitar_candidate.exists() else None

    return SeparationResult(vocals_path=vocals_path, guitar_path=guitar_path)


def transcribe_lyrics_with_timestamps(
    vocals_path: Path,
    model_size: str = "medium",
    language: Optional[str] = None,
) -> LyricsResult:
    if not vocals_path.exists():
        raise FileNotFoundError(f"보컬 오디오 파일을 찾을 수 없습니다: {vocals_path}")

    device = "cuda" if has_cuda() else "cpu"

    model = whisper.load_model(model_size, device=device)

    # Whisper는 내부적으로 ffmpeg를 사용하므로, ffmpeg가 PATH에 있어야 한다.
    result = model.transcribe(
        str(vocals_path),
        language=language,
        verbose=False,
    )

    full_text = result.get("text", "") or ""
    segments_raw = result.get("segments", []) or []

    segments: List[LyricSegment] = []
    for seg in segments_raw:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        text = str(seg.get("text", "")).strip()
        segments.append(LyricSegment(start=start, end=end, text=text))

    return LyricsResult(
        full_text=full_text,
        segments=segments,
        model_name=model_size,
        device=device,  # type: ignore[arg-type]
    )


def lyrics_result_to_json(result: LyricsResult) -> str:
    return json.dumps(
        {
            "full_text": result.full_text,
            "model_name": result.model_name,
            "device": result.device,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in result.segments
            ],
        },
        ensure_ascii=False,
    )

