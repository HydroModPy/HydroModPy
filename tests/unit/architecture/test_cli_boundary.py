"""Seal the CLI boundary.

Only the dispatcher entry point ``hydromodpy.__main__`` may import from the
CLI package. Every other module under ``hydromodpy/`` (and every file under
``tests/`` outside of CLI integration tests) must not depend on the CLI
implementation. The lint covers both the current on-disk name ``_cli`` and
the post-rename target ``cli`` (S07-01) so it stays valid through the
rename.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.audit.build_graph import parse_imports  # noqa: E402

CLI_PACKAGES: tuple[str, ...] = ("hydromodpy._cli", "hydromodpy.cli")

WHITELIST: frozenset[str] = frozenset(
    {
        "hydromodpy/__main__.py",
    }
)


def _is_cli_target(module: str) -> bool:
    return any(module == pkg or module.startswith(f"{pkg}.") for pkg in CLI_PACKAGES)


def _is_inside_cli(rel: str) -> bool:
    return rel.startswith("hydromodpy/_cli/") or rel.startswith("hydromodpy/cli/")


def test_cli_boundary_sealed() -> None:
    """No ``hydromodpy/`` module outside ``_cli/`` (or the whitelist) may import CLI code."""
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
            "CLI boundary breach — only hydromodpy/__main__.py may import from "
            "hydromodpy._cli / hydromodpy.cli:\n" + "\n".join(f"  {o}" for o in offenders)
        )
