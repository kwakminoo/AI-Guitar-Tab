"""
YouTube URL 가드·yt-dlp --no-playlist 회귀.
ML 의존성 없이 실행: PYTHONPATH=. python3 scripts/test_youtube_url_guard.py
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _load_is_supported_youtube_url():
    """pretty_midi 등 미설치 환경에서도 main.py 함수만 AST로 적재한다."""
    main_path = _BACKEND / "app" / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    fn_node = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_is_supported_youtube_url":
            fn_node = node
            break
    if fn_node is None:
        raise AssertionError("_is_supported_youtube_url 를 main.py 에서 찾지 못했습니다.")

    mod = types.ModuleType("youtube_url_guard_test_mod")
    mod.urlparse = urlparse
    mod.parse_qs = parse_qs
    # py3.11+: FunctionDef 단독 exec용 모듈
    wrapper = ast.Module(body=[fn_node], type_ignores=[])
    ast.fix_missing_locations(wrapper)
    exec(compile(wrapper, str(main_path), "exec"), mod.__dict__)
    return mod._is_supported_youtube_url


def test_url_allow_and_reject() -> None:
    is_ok = _load_is_supported_youtube_url()

    allowed = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&list=PLdeadbeef",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
    ]
    rejected = [
        "https://www.youtube.com/playlist?list=PLdeadbeef",
        "https://youtube.com/playlist?list=PLdeadbeef",
        "https://www.youtube.com/",
        "https://www.youtube.com/results?search_query=guitar",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/",
    ]
    for url in allowed:
        assert is_ok(url), f"허용되어야 함: {url}"
    for url in rejected:
        assert not is_ok(url), f"거부되어야 함: {url}"


def test_yt_dlp_commands_include_no_playlist() -> None:
    pipeline_src = (_BACKEND / "app" / "services" / "pipeline.py").read_text(encoding="utf-8")
    # yt_dlp 모듈 호출 블록마다 --no-playlist 가 있어야 한다.
    marker = '"yt_dlp"'
    idx = 0
    hits = 0
    while True:
        found = pipeline_src.find(marker, idx)
        if found < 0:
            break
        hits += 1
        window = pipeline_src[found : found + 350]
        assert "--no-playlist" in window, (
            f"yt_dlp 호출 #{hits} 근처에 --no-playlist 가 없습니다:\n{window}"
        )
        idx = found + len(marker)
    assert hits >= 3, f"yt_dlp 호출이 예상보다 적음: {hits}"


if __name__ == "__main__":
    test_url_allow_and_reject()
    test_yt_dlp_commands_include_no_playlist()
    print("ok")
