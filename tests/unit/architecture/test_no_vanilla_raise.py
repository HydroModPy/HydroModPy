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
    "project/facade.py",
    "workflow",
    "solver/base/runner.py",
    "solver/base/rerun.py",
    "solver/modflow_common/flow_adapter_helpers.py",
    "solver/modflow_common/mt3dms_extractor_base.py",
    "solver/modflow6/adapter.py",
    "solver/modflow6/rerun.py",
    "solver/modflow6/transport.py",
    "solver/modflow6/prt.py",
    "solver/modflow_nwt/adapter.py",
    "solver/modflow_nwt/mt3dms/mt3dms.py",
    "solver/modflow_nwt/modpath/modpath.py",
    "solver/boussinesq/adapter.py",
)
"""Files and folders, relative to the package, that raise typed exceptions only. Each must exist."""

EXEMPT: dict[str, dict[str, str]] = {
    "solver/modflow6/transport.py": {
        "why": "legacy engine class Modflow6Gwt raises RuntimeError before solve",
        "lifted_by": "4.16",
    },
    "solver/modflow6/prt.py": {
        "why": "legacy engine class Modflow6Prt raises ValueError/RuntimeError",
        "lifted_by": "4.16",
    },
    "solver/modflow_nwt/mt3dms/mt3dms.py": {
        "why": "legacy engine class Mt3dms raises ValueError/RuntimeError",
        "lifted_by": "4.16",
    },
    "solver/modflow_nwt/modpath/modpath.py": {
        "why": "legacy engine class Modpath raises ValueError",
        "lifted_by": "4.16",
    },
}
"""Files inside a scoped folder that keep their vanilla raises for now.

Each entry says why and names the lot that lifts it, like ``known_stale`` in
``dotted_paths.yaml``. An entry whose file no longer raises a vanilla exception
fails the gate, so it leaves as soon as it is lifted. The list is empty.
"""

BANNED: frozenset[str] = frozenset({"ValueError", "RuntimeError"})

NOT_FAILURES: frozenset[str] = frozenset(
    {"ConfigKeyRenamedWarning", "StopRequested", "TerminationRequested"}
)
"""A warning is no failure. A signal, and a stop asked through the flag of a run, must
stay out of reach of ``except Exception``."""

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
    return [f for f in files if f.relative_to(PKG_ROOT).as_posix() not in EXEMPT]


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


def test_every_exemption_is_dated_and_still_needed() -> None:
    """An exempt file names its lifting lot and still holds a vanilla raise.

    One test over the whole table, so an empty table passes rather than skips.
    """
    for entry, exemption in EXEMPT.items():
        assert exemption.get("why") and exemption.get("lifted_by"), entry
        path = PKG_ROOT / entry
        assert path.is_file(), f"{entry} is gone: drop its exemption"
        assert _vanilla_raises(path), f"{entry} raises no vanilla exception: drop its exemption"


@pytest.mark.parametrize("entry", SCOPE)
def test_every_scoped_entry_exists(entry: str) -> None:
    """A moved file would leave the scope in silence, as the old Boussinesq adapter path did."""
    assert (PKG_ROOT / entry).exists(), f"{entry} is not in the package: update SCOPE"
