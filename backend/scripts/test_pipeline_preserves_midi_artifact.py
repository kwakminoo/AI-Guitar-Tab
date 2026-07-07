"""
Regression check: the YouTube pipeline must not overwrite the raw Basic Pitch MIDI.

Run from the repository root:
    python3 backend/scripts/test_pipeline_preserves_midi_artifact.py
"""

from __future__ import annotations

import ast
from pathlib import Path


PIPELINE_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "pipeline.py"


def _is_str_midi_path_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "midi_path"
    )


def _find_in_place_midi_writes(tree: ast.AST) -> list[int]:
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "run_four_step_pipeline":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Attribute) or child.func.attr != "write":
                continue
            if child.args and _is_str_midi_path_call(child.args[0]):
                offenders.append(child.lineno)
    return offenders


def main() -> None:
    tree = ast.parse(PIPELINE_PATH.read_text(encoding="utf-8"))
    offenders = _find_in_place_midi_writes(tree)
    assert not offenders, (
        "run_four_step_pipeline must preserve the raw Basic Pitch MIDI; "
        f"found in-place write(s) to midi_path at line(s): {offenders}"
    )
    print("pipeline preserves raw MIDI artifact: ok")


if __name__ == "__main__":
    main()
