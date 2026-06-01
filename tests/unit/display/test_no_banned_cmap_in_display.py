"""No figure hard-codes a banned colormap name.

Scans every ``hydromodpy/display/figures/*.py`` and every renderer helper
for string literals that match a banned cmap name (``jet``, ``rainbow``,
``hsv``, ``nipy_spectral``, ``gist_rainbow``).
"""

from __future__ import annotations

import ast
from pathlib import Path

from hydromodpy.display.colormaps import BANNED_CMAPS


def _figure_files() -> list[Path]:
    root = Path(__file__).resolve().parents[3] / "hydromodpy" / "display"
    return sorted(p for p in root.rglob("*.py") if p.is_file() and "__pycache__" not in p.parts)


def test_no_banned_cmap_literal() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    offending: list[tuple[str, int, str]] = []
    for path in _figure_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in BANNED_CMAPS:
                    # The colormaps.py module itself is allowed to list them.
                    if path.name == "colormaps.py":
                        continue
                    offending.append(
                        (path.relative_to(repo_root).as_posix(), node.lineno, node.value)
                    )
    assert not offending, (
        f"Display files use banned cmap literal(s): {offending}. "
        f"Use one of the perceptually-uniform alternatives instead."
    )
