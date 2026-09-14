"""The api-isolation switch must not drag a backend onto the calibration path.

``run_calibration_core`` wraps its whole ask/tell loop in ``api_isolation_context``
whatever backend the run selected. The switch itself is a ``ContextVar``: it holds
no solver state and needs none. Importing it must therefore cost nothing, so a
Boussinesq or a lumped calibration does not require a MODFLOW binding to exist.

Checked on the import graph rather than on ``sys.modules``: a runtime probe only
says what this interpreter happened to have loaded, while the import list says
what the module can ever pull in.
"""

from __future__ import annotations

import ast
from pathlib import Path

import hydromodpy.solver.base.api_isolation as isolation

_BACKENDS = ("modflow", "flopy", "boussinesq")


def _imported_modules(module: object) -> set[str]:
    """Every module name the file imports, at module level or inside a function."""
    source_file = getattr(module, "__file__", None)
    assert source_file is not None, f"{module!r} has no source file to read"
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_the_switch_carries_the_intent_and_nothing_else() -> None:
    """The context manager sets, exposes and restores the flag."""
    assert isolation.api_isolation_enabled() is False
    with isolation.api_isolation_context(True):
        assert isolation.api_isolation_enabled() is True
    assert isolation.api_isolation_enabled() is False


def test_the_switch_imports_no_backend() -> None:
    """Its own module names no backend, so importing it loads none."""
    imported = _imported_modules(isolation)
    assert not [name for name in imported if any(b in name for b in _BACKENDS)]


def test_calibration_core_reaches_the_switch_without_a_backend() -> None:
    """The shared calibration runner imports the switch from the neutral module."""
    from hydromodpy.calibration.runners import cli_runner

    imported = _imported_modules(cli_runner)
    assert "hydromodpy.solver.base.api_isolation" in imported
    assert not [name for name in imported if any(b in name for b in _BACKENDS)]
