"""No figure hard-codes a banned colormap name.

Scans every ``hydromodpy/display/figures/*.py`` and every renderer helper
for string literals that match a banned cmap name (``jet``, ``rainbow``,
``hsv``, ``nipy_spectral``, ``gist_rainbow``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hydromodpy.display.colormaps import BANNED_CMAPS


def _figure_files() -> list[Path]:
    root = Path(__file__).resolve().parents[3] / "hydromodpy" / "display"
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


@pytest.mark.parametrize("path", _figure_files(), ids=lambda p: p.name)
def test_no_banned_cmap_literal(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offending: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in BANNED_CMAPS:
                # The colormaps.py module itself is allowed to list them.
                if path.name == "colormaps.py":
                    continue
                offending.append((node.lineno, node.value))
    assert not offending, (
        f"{path} uses banned cmap literal(s): {offending}. "
        f"Use one of the perceptually-uniform alternatives instead."
    )
