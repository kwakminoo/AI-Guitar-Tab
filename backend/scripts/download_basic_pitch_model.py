from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dest = (
        repo_root
        / "backend"
        / "app"
        / "models"
        / "basic_pitch"
        / "saved_models"
        / "icassp_2022"
        / "nmp.onnx"
    )

    if dest.exists() and dest.stat().st_size > 0:
        return

    with tempfile.TemporaryDirectory(prefix="basic_pitch_dl_") as tmp:
        tmp_path = Path(tmp)

        # 모델 파일 추출 목적: 설치는 하지 않고 wheel만 다운로드
        pkg_spec = "basic-pitch[onnx]>=0.4.0"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--no-deps",
                "-d",
                str(tmp_path),
                pkg_spec,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        wheels = sorted(tmp_path.glob("*.whl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not wheels:
            raise RuntimeError("basic-pitch wheel을 다운로드하지 못했습니다.")

        wheel_path = wheels[0]

        members: list[str] = []
        with zipfile.ZipFile(wheel_path, "r") as z:
            for name in z.namelist():
                if "basic_pitch/saved_models/icassp_2022" in name and name.endswith("nmp.onnx"):
                    members.append(name)

            if not members:
                # 예외적으로 다른 위치/파일명이면 여기서 확장자를 기준으로 재탐색
                for name in z.namelist():
                    if name.endswith("nmp.onnx") and "saved_models/icassp_2022" in name:
                        members.append(name)

            if not members:
                raise RuntimeError("wheel 안에서 icassp_2022/nmp.onnx를 찾지 못했습니다.")

            member = sorted(members)[0]

            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, open(dest, "wb") as f:
                shutil.copyfileobj(src, f)


if __name__ == "__main__":
    main()

