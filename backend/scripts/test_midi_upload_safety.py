"""
MIDI 업로드 안전성 회귀 테스트.
실행: backend 디렉터리에서  PYTHONPATH=. python scripts/test_midi_upload_safety.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path


class StubHTTPException(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class StubFastAPI:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def add_middleware(self, *args: object, **kwargs: object) -> None:
        pass

    def get(self, *args: object, **kwargs: object):
        return lambda fn: fn

    def post(self, *args: object, **kwargs: object):
        return lambda fn: fn


class StubBaseModel:
    pass


def _install_dependency_stubs() -> None:
    fastapi_mod = types.ModuleType("fastapi")
    fastapi_mod.FastAPI = StubFastAPI
    fastapi_mod.File = lambda *args, **kwargs: None
    fastapi_mod.HTTPException = StubHTTPException
    fastapi_mod.UploadFile = object
    sys.modules["fastapi"] = fastapi_mod

    cors_mod = types.ModuleType("fastapi.middleware.cors")
    cors_mod.CORSMiddleware = object
    sys.modules["fastapi.middleware"] = types.ModuleType("fastapi.middleware")
    sys.modules["fastapi.middleware.cors"] = cors_mod

    pydantic_mod = types.ModuleType("pydantic")
    pydantic_mod.BaseModel = StubBaseModel
    pydantic_mod.HttpUrl = str
    sys.modules["pydantic"] = pydantic_mod

    pipeline_mod = types.ModuleType("app.services.pipeline")
    pipeline_mod._midi_to_alphatex = lambda *args, **kwargs: ""
    pipeline_mod._midi_to_score = lambda *args, **kwargs: {}
    pipeline_mod.run_four_step_pipeline = lambda *args, **kwargs: None
    sys.modules["app.services.pipeline"] = pipeline_mod


_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_install_dependency_stubs()

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


class MidiUploadSafetyTests(unittest.TestCase):
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

        with self.assertRaises(StubHTTPException) as ctx:
            asyncio.run(app_main._read_midi_upload_limited(upload))

        self.assertEqual(ctx.exception.status_code, 413)

    def test_creates_distinct_upload_dirs_for_same_filename(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            uploads_dir = Path(td)

            first = app_main._create_midi_upload_dir(uploads_dir, "same.mid")
            second = app_main._create_midi_upload_dir(uploads_dir, "same.mid")

        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, second.parent)
        self.assertTrue(first.name.startswith("same-"))
        self.assertTrue(second.name.startswith("same-"))


if __name__ == "__main__":
    unittest.main()
