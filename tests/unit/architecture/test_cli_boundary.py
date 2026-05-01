"""Seal the CLI boundary.

Only the dispatcher entry point ``hydromodpy.__main__`` may import from the
CLI package. Every other module under ``hydromodpy/`` (and every file under
``tests/`` outside of CLI integration tests) must not depend on the CLI
implementation.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"

_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_BUILD_GRAPH_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_cli_boundary_build_graph",
    _BUILD_GRAPH_PATH,
)
if _BUILD_GRAPH_SPEC is None or _BUILD_GRAPH_SPEC.loader is None:
    raise RuntimeError(f"Could not load architecture scanner at {_BUILD_GRAPH_PATH}")
_BUILD_GRAPH_MODULE = importlib.util.module_from_spec(_BUILD_GRAPH_SPEC)
sys.modules[_BUILD_GRAPH_SPEC.name] = _BUILD_GRAPH_MODULE
_BUILD_GRAPH_SPEC.loader.exec_module(_BUILD_GRAPH_MODULE)

parse_imports = _BUILD_GRAPH_MODULE.parse_imports

CLI_PACKAGE: str = "hydromodpy.cli"

WHITELIST: frozenset[str] = frozenset(
    {
        "hydromodpy/__main__.py",
    }
)


def _is_cli_target(module: str) -> bool:
    return module == CLI_PACKAGE or module.startswith(f"{CLI_PACKAGE}.")


def _is_inside_cli(rel: str) -> bool:
    return rel.startswith("hydromodpy/cli/")


def test_cli_boundary_sealed() -> None:
    """No ``hydromodpy/`` module outside ``cli/`` (or the whitelist) may import CLI code."""
    offenders: list[str] = []
    for py in sorted(PKG_ROOT.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(REPO_ROOT).as_posix()
        if _is_inside_cli(rel) or rel in WHITELIST:
            continue
        for lineno, _kind, module in parse_imports(py, PKG_ROOT):
            if _is_cli_target(module):
                offenders.append(f"{rel}:{lineno} imports {module}")
    if offenders:
        pytest.fail(
            "CLI boundary breach: only hydromodpy/__main__.py may import from "
            "hydromodpy.cli:\n" + "\n".join(f"  {o}" for o in offenders)
        )
