from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import yt_dlp


@dataclass(frozen=True)
class DownloadResult:
    id: str
    wav_path: Path


class AudioService:
    def __init__(self, output_dir: Path):
        self._output_dir = output_dir

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def download_youtube_to_wav(self, youtube_url: str) -> DownloadResult:
        self._output_dir.mkdir(parents=True, exist_ok=True)

        file_id = str(uuid.uuid4())
        outtmpl = str((self._output_dir / f"{file_id}.%(ext)s").resolve())

        ydl_opts: dict = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "outtmpl": outtmpl,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                    "preferredquality": "0",
                }
            ],
            "overwrites": False,
            "windowsfilenames": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        wav_path = (self._output_dir / f"{file_id}.wav").resolve()
        if not wav_path.exists():
            raise RuntimeError("다운로드는 완료됐지만 WAV 파일을 찾지 못했습니다. FFmpeg 설치/경로를 확인하세요.")

        return DownloadResult(id=file_id, wav_path=wav_path)


def default_audio_dir() -> Path:
    # app/services/audio_service.py -> app/services -> app -> project root
    return Path(__file__).resolve().parents[2] / "data" / "audio"

