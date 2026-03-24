from __future__ import annotations

from pathlib import Path
import subprocess


def extract_guitar_stem(input_audio: Path, output_dir: Path) -> Path:
    """
    Demucs CLI를 사용해 입력 오디오에서 기타(guitar) 스템을 추출한다.
    - demucs 패키지가 설치되어 있고, 가상환경의 스크립트 경로에서 찾을 수 있어야 한다.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # htdemucs_6s 모델은 기타 스템을 포함한 6개 소스를 분리한다.
    # demucs -n htdemucs_6s -o <output_dir> <input_audio>
    try:
        subprocess.run(
            [
                "demucs",
                "-n",
                "htdemucs_6s",
                "-o",
                str(output_dir),
                str(input_audio),
            ],
            check=True,
            timeout=240,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Demucs 실행에 실패하면 일단 원본 오디오를 그대로 사용한다.
        return input_audio

    # Demucs 출력 구조: <output_dir>/<model_name>/<basename>/<stem>.wav
    # 예: output_dir/htdemucs_6s/trackname/guitar.wav
    model_dir = output_dir / "htdemucs_6s"
    if not model_dir.exists():
        return input_audio

    # 가장 최근 생성된 트랙 디렉터리를 선택
    track_dirs = sorted(
        [p for p in model_dir.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not track_dirs:
        return input_audio

    candidate = track_dirs[0] / "guitar.wav"
    if candidate.exists():
        return candidate

    # guitar.wav 이 없으면, 다른 스템(예: other.wav)을 대체로 사용
    fallback = track_dirs[0] / "other.wav"
    return fallback if fallback.exists() else input_audio

