"""Platform-determinism gates for the capability-gallery generator.

``python -m tools.doc_gallery --check`` compares regenerated artifacts against the
committed ones byte for byte, so anything the generator writes has to be identical
on Linux and on Windows.

Two hazards are covered here. A text writer left on the default newline
translation emits CRLF on Windows and LF on Linux. And a provenance digest taken
over the raw bytes of a text source follows the line endings Git materialised at
checkout, which are CRLF on a Windows worktree for the very same commit.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from tools.doc_gallery import update_gallery

TOOL_ROOT = Path(update_gallery.__file__).resolve().parent
TEXT_WRITE_MODES = frozenset("wax+")
WRITE_CALL_NAMES = frozenset({"write_text", "open", "_open_file"})


def _is_text_write_mode(mode: str) -> bool:
    return "b" not in mode and bool(TEXT_WRITE_MODES & set(mode))


def _mode_argument(node: ast.Call, mode_index: int) -> ast.expr | None:
    if len(node.args) > mode_index:
        return node.args[mode_index]
    for keyword in node.keywords:
        if keyword.arg == "mode":
            return keyword.value
    return None


def _called_name_and_mode(node: ast.Call) -> tuple[str, ast.expr | None] | None:
    """Return the callee name and its mode argument, if the call can write text."""
    if isinstance(node.func, ast.Attribute):
        name = node.func.attr
        mode_index = 0
    elif isinstance(node.func, ast.Name):
        name = node.func.id
        mode_index = 1
    else:
        return None
    if name not in WRITE_CALL_NAMES:
        return None
    if name == "write_text":
        return name, None
    return name, _mode_argument(node, mode_index)


def _writers_without_explicit_newline(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _called_name_and_mode(node)
        if called is None:
            continue
        name, mode = called
        if "newline" in {keyword.arg for keyword in node.keywords}:
            continue
        if name == "write_text":
            offenders.append(f"{module_path.name}:{node.lineno} write_text")
            continue
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
            if _is_text_write_mode(mode.value):
                offenders.append(f"{module_path.name}:{node.lineno} open({mode.value!r})")
    return offenders


def test_doc_gallery_text_writers_pin_the_newline() -> None:
    offenders: list[str] = []
    for module_path in sorted(TOOL_ROOT.rglob("*.py")):
        offenders.extend(_writers_without_explicit_newline(module_path))

    assert offenders == [], 'Text writers must pass newline="\\n": ' + ", ".join(offenders)


def test_write_text_emits_lf_only(tmp_path: Path) -> None:
    target = tmp_path / "page.rst"

    update_gallery._write_text(target, "first\nsecond\n")

    assert update_gallery._read_bytes(target) == b"first\nsecond\n"


def test_write_json_emits_lf_only(tmp_path: Path) -> None:
    target = tmp_path / "summary.json"

    update_gallery._write_json(target, {"slug": "alpha", "images": ["a.png", "b.png"]})

    payload = update_gallery._read_bytes(target)
    assert b"\r" not in payload
    assert payload.endswith(b"}\n")


def test_sha256_ignores_the_checkout_line_endings(tmp_path: Path) -> None:
    lf_source = tmp_path / "module_lf.py"
    crlf_source = tmp_path / "module_crlf.py"
    lf_source.write_bytes(b"import os\n\n\nVALUE = 1\n")
    crlf_source.write_bytes(b"import os\r\n\r\n\r\nVALUE = 1\r\n")

    assert update_gallery._sha256(crlf_source) == update_gallery._sha256(lf_source)


def test_sha256_of_a_text_source_matches_its_lf_bytes(tmp_path: Path) -> None:
    crlf_source = tmp_path / "manifest.json"
    crlf_source.write_bytes(b'{\r\n  "slug": "alpha"\r\n}\r\n')

    expected = hashlib.sha256(b'{\n  "slug": "alpha"\n}\n').hexdigest()

    assert update_gallery._sha256(crlf_source) == expected


def test_sha256_keeps_binary_sources_byte_exact(tmp_path: Path) -> None:
    payload = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\r\n"
    binary_source = tmp_path / "figure.png"
    binary_source.write_bytes(payload)

    assert update_gallery._sha256(binary_source) == hashlib.sha256(payload).hexdigest()
