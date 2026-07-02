"""
MIDI 업로드 크기 제한 테스트.
실행: backend 디렉터리에서  PYTHONPATH=. python scripts/test_midi_upload_limits.py
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

from fastapi import HTTPException

# backend 루트를 path에 추가
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app import main as app_main  # noqa: E402


class FakeUpload:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        if size < 0 or len(chunk) <= size:
            return chunk
        self._chunks.insert(0, chunk[size:])
        return chunk[:size]


class MidiUploadLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_limit = app_main.MAX_MIDI_UPLOAD_BYTES
        self._old_chunk = app_main._MIDI_UPLOAD_READ_CHUNK_BYTES
        app_main.MAX_MIDI_UPLOAD_BYTES = 10
        app_main._MIDI_UPLOAD_READ_CHUNK_BYTES = 4

    def tearDown(self) -> None:
        app_main.MAX_MIDI_UPLOAD_BYTES = self._old_limit
        app_main._MIDI_UPLOAD_READ_CHUNK_BYTES = self._old_chunk

    def test_reads_upload_at_limit(self) -> None:
        upload = FakeUpload([b"abcd", b"efghij"])

        data = asyncio.run(app_main._read_midi_upload_limited(upload))

        self.assertEqual(data, b"abcdefghij")

    def test_rejects_upload_over_limit(self) -> None:
        upload = FakeUpload([b"abcd", b"efgh", b"ijk"])

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(app_main._read_midi_upload_limited(upload))

        self.assertEqual(ctx.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
