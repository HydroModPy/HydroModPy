"""Typed exceptions: every public one has the root, and scoped layers raise no vanilla one.

The first part walks the classes of the package: an exception a caller can meet derives
from ``HydroModPyError``, so ``except hmp.HydroModPyError`` means what it says.

The second part bans ``raise ValueError`` / ``raise RuntimeError`` in scoped layers.

Ruff has no built-in rule that targets these specific exception names, so
this AST-based architecture test enforces the typed-exception contract for
the modules covered by S05-05. Each new module that should be locked down
adds itself to ``SCOPE``. ``hydromodpy/`` outside this scope keeps its
historical raises until later sessions migrate them; tests/ are out of
scope by design (whitelist).
"""

from __future__ import annotations

import ast
import builtins
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

NOT_FAILURES: frozenset[str] = frozenset({"ConfigKeyRenamedWarning", "TerminationRequested"})
"""A warning is no failure, and a signal must stay out of reach of ``except Exception``."""

ROOT = "HydroModPyError"


def _classes_with_bases() -> dict[str, set[str]]:
    """Return the base names of every class the package defines, by class name."""
    bases: dict[str, set[str]] = {}
    for file in PKG_ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                names = {
                    base.id if isinstance(base, ast.Name) else base.attr
                    for base in node.bases
                    if isinstance(base, ast.Name | ast.Attribute)
                }
                bases.setdefault(node.name, set()).update(names)
    return bases


def test_a_public_exception_derives_from_the_root() -> None:
    """A leading underscore keeps a control-flow exception inside its module."""
    bases = _classes_with_bases()

    def reaches(name: str, target: set[str]) -> bool:
        return name in target or any(reaches(base, target) for base in bases.get(name, ()))

    builtin = {name for name, value in vars(builtins).items() if isinstance(value, type)}
    failures = {name for name in builtin if issubclass(getattr(builtins, name), BaseException)}
    outside = sorted(
        name
        for name in bases
        if not name.startswith("_")
        and name not in NOT_FAILURES
        and reaches(name, failures)
        and not reaches(name, {ROOT})
    )
    assert outside == [], f"{outside} do not derive from {ROOT}: add a family of core.exceptions."


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
