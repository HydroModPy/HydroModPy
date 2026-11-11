"""A warning a document can raise goes through ``say``, so ``check`` collects it.

``check`` reads warnings from the sink of ``core/config_kit/said.py``, never
from the filter of the process, because two threads share that filter. A
``warnings.warn`` in a validator would leave the diagnostics of ``check`` and
reach stderr or the log of the server. This test refuses it in every module
that sets a pydantic validator, in ``config/`` and ``core/config_kit/``, and
in the modules ``check`` reaches through a section.
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"

VALIDATORS = frozenset(
    {"field_validator", "model_validator", "BeforeValidator", "AfterValidator", "WrapValidator"}
)
FOLDERS = ("config", "core/config_kit")
REACHED_BY_CHECK = ("calibration/parameter_resolution.py", "core/time/window.py")
THE_SINK = "core/config_kit/said.py"


def _names(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            found.update(alias.name for alias in node.names)
    return found


def _warns(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "warn"
            and isinstance(func.value, ast.Name)
            and func.value.id == "warnings"
        ):
            lines.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id == "warn":
            lines.append(node.lineno)
    return lines


def _in_scope(relative: str, tree: ast.AST) -> bool:
    if relative in REACHED_BY_CHECK:
        return True
    if any(relative.startswith(folder + "/") for folder in FOLDERS):
        return True
    return bool(_names(tree) & VALIDATORS)


def test_a_module_a_document_reaches_says_its_warnings() -> None:
    offenders = []
    seen = 0
    for path in sorted(PKG_ROOT.rglob("*.py")):
        relative = path.relative_to(PKG_ROOT).as_posix()
        if relative == THE_SINK:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not _in_scope(relative, tree):
            continue
        seen += 1
        offenders.extend(f"{relative}:{line}" for line in _warns(tree))

    assert seen > 20, "the scan found too few modules: check PKG_ROOT"
    assert not offenders, (
        "call hydromodpy.core.config_kit.said.say instead of warnings.warn: " + ", ".join(offenders)
    )


def test_the_scan_sees_a_warn_and_a_validator() -> None:
    tree = ast.parse(
        "import warnings\nfrom pydantic import field_validator\nwarnings.warn('a')\nwarn('b')\n"
    )

    assert _in_scope("model/x.py", tree)
    assert _warns(tree) == [3, 4]
    assert not _in_scope("model/x.py", ast.parse("import warnings\nwarnings.warn('a')\n"))
    for relative in REACHED_BY_CHECK:
        assert (PKG_ROOT / relative).is_file()
