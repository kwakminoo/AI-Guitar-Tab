"""유튜브 자막 폴백이 시간 초과여도 탭 파이프라인을 끊지 않는지 확인한다."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.pipeline import (  # noqa: E402
    _resolve_youtube_lyrics,
    _youtube_subtitle_fallback_lyrics,
)


def _timeout(*_args: object, **_kwargs: object) -> None:
    raise subprocess.TimeoutExpired(cmd=["yt-dlp"], timeout=180)


class SubtitleFallbackTimeoutTest(unittest.TestCase):
    def test_timeout_without_vtt_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch("app.services.pipeline.subprocess.run", side_effect=_timeout):
                text = _youtube_subtitle_fallback_lyrics("https://www.youtube.com/watch?v=abc", Path(td))
        self.assertIsNone(text)

    def test_timeout_keeps_partial_vtt(self) -> None:
        lyrics = "\n".join(
            [
                "WEBVTT",
                "",
                "00:00:01.000 --> 00:00:03.000",
                "첫 줄 가사는 충분히 길게 적습니다",
                "",
                "00:00:03.000 --> 00:00:05.000",
                "둘째 줄도 자막으로 남습니다",
            ]
        )

        def write_then_timeout(*_args, **_kwargs) -> None:
            out = Path(td) / "vid.ko.vtt"
            out.write_text(lyrics, encoding="utf-8")
            _timeout()

        with tempfile.TemporaryDirectory() as td:
            with patch("app.services.pipeline.subprocess.run", side_effect=write_then_timeout):
                text = _youtube_subtitle_fallback_lyrics("https://www.youtube.com/watch?v=abc", Path(td))
        self.assertIsNotNone(text)
        assert text is not None
        self.assertIn("첫 줄 가사는 충분히 길게 적습니다", text)
        self.assertIn("둘째 줄도 자막으로 남습니다", text)

    def test_resolve_lyrics_continues_after_subtitle_timeout(self) -> None:
        description = "첫 문단 첫째 줄\n첫 문단 둘째 줄입니다\n\n다음 문단"
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            with (
                patch(
                    "app.services.pipeline.fetch_lyrics_from_lrclib",
                    return_value=(None, "none"),
                ),
                patch("app.services.pipeline.subprocess.run", side_effect=_timeout),
            ):
                text, src = _resolve_youtube_lyrics(
                    "https://www.youtube.com/watch?v=abc",
                    job,
                    "Artist - Song",
                    None,
                    None,
                    description,
                    None,
                    None,
                    job / "cache",
                )
        self.assertEqual(src, "youtube_description")
        self.assertIsNotNone(text)
        assert text is not None
        self.assertIn("첫 문단 첫째 줄", text)


if __name__ == "__main__":
    unittest.main()
