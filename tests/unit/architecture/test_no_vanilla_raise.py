"""Ban ``raise ValueError`` / ``raise RuntimeError`` in scoped layers.

Ruff has no built-in rule that targets these specific exception names, so
this AST-based architecture test enforces the typed-exception contract for
the modules covered by S05-05. Each new module that should be locked down
adds itself to ``SCOPE``. ``hydromodpy/`` outside this scope keeps its
historical raises until later sessions migrate them; tests/ are out of
scope by design (whitelist).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"

SCOPE: tuple[str, ...] = (
    "project.py",
    "workflow",
    "solver/modflow_common/flow_adapter_helpers.py",
    "solver/boussinesq/adapters/flow.py",
    "solver/modflow6/adapters/transport.py",
    "solver/modflow_nwt/adapters/transport_modpath.py",
    "solver/modflow_nwt/adapters/transport_mt3dms.py",
)

BANNED: frozenset[str] = frozenset({"ValueError", "RuntimeError"})


def _scoped_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for entry in SCOPE:
        target = PKG_ROOT / entry
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(target.rglob("*.py"))
    return files


def _vanilla_raises(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        target = node.exc
        if isinstance(target, ast.Call):
            target = target.func
        name = target.id if isinstance(target, ast.Name) else None
        if name in BANNED:
            found.append((node.lineno, name))
    return found


def test_scope_uses_typed_exceptions() -> None:
    """Scoped modules must raise typed HMPY exceptions, never vanilla ones."""
    offenders: list[str] = []
    for file in _scoped_files():
        for lineno, name in _vanilla_raises(file):
            rel = file.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}:{lineno} raise {name}")
    if offenders:
        pytest.fail(
            "Vanilla `raise ValueError|RuntimeError` is forbidden in S05-05 scope.\n"
            "Use a typed exception from hydromodpy.core.exceptions instead:\n"
            + "\n".join(f"  {line}" for line in offenders)
        )
