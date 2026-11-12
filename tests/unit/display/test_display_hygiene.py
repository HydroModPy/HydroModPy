"""The display package keeps no banned colormap, hardcoded EPSG or matplotlib side effect.

The first two checks scan the source text of ``hydromodpy/display`` (and
``project/compare.py`` for EPSG). The third imports the package afresh and
compares the matplotlib rcParams before and after.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

from hydromodpy.display.style import BANNED_CMAPS

REPO_ROOT = Path(__file__).resolve().parents[3]
HMP_ROOT = REPO_ROOT / "hydromodpy"

# ``crs="EPSG:2154"``, ``crs='EPSG:2154'`` and ``epsg=2154`` keyword arguments.
HARDCODE_PATTERNS = (
    re.compile(r'crs\s*=\s*"EPSG:\d+"'),
    re.compile(r"crs\s*=\s*'EPSG:\d+'"),
    re.compile(r"epsg\s*=\s*\d+"),
)

TARGETS = ("display", "project/compare.py")

# (file suffix, line substring) pairs of legitimate uses. A hit is skipped only
# when it matches both.
WHITELIST: tuple[tuple[str, str], ...] = (
    # _write_geotiff has a crs_arg fallback after `if crs is None: crs_arg = "EPSG:2154"`.
    ("comparison/visuals_render_maps.py", 'crs_arg: str = "EPSG:2154"'),
    # Hub'Eau lon/lat fallback.
    ("display/overview/panels.py", 'src_crs = p.get("crs") or "EPSG:4326"'),
)


def display_files() -> list[Path]:
    root = HMP_ROOT / "display"
    return sorted(p for p in root.rglob("*.py") if p.is_file() and "__pycache__" not in p.parts)


def is_whitelisted(path: Path, line: str) -> bool:
    return any(path.as_posix().endswith(suffix) and text in line for suffix, text in WHITELIST)


def hardcoded_epsg(target: Path) -> list[str]:
    found: list[str] = []
    for path in [target] if target.is_file() else target.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = raw_line.strip()
            # Comment lines and the first line of a docstring are skipped.
            if not stripped or stripped.startswith(("#", '"""', "'''")):
                continue
            if any(p.search(raw_line) for p in HARDCODE_PATTERNS) and not is_whitelisted(
                path, raw_line
            ):
                found.append(f"{path}:{lineno}: {raw_line.rstrip()}")
    return found


def test_no_banned_cmap_literal() -> None:
    offending: list[tuple[str, int, str]] = []
    for path in display_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative == "hydromodpy/display/style.py":  # it declares the banned list
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in BANNED_CMAPS:
                offending.append((relative, node.lineno, node.value))

    assert not offending, f"banned cmap literal(s) in display files: {offending}"


def test_no_hardcoded_epsg_in_display_and_compare() -> None:
    offending = [line for sub in TARGETS for line in hardcoded_epsg(HMP_ROOT / sub)]

    assert not offending, "hard-coded EPSG literals found:\n" + "\n".join(offending)


def test_display_import_does_not_mutate_rcparams() -> None:
    import matplotlib

    before = dict(matplotlib.rcParams)
    display_modules = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith("hydromodpy.display")
    }

    try:
        # A fresh import runs the module-level code of every display module.
        for mod in list(sys.modules):
            if mod.startswith("hydromodpy.display"):
                del sys.modules[mod]
        importlib.import_module("hydromodpy.display")
    finally:
        for mod in list(sys.modules):
            if mod.startswith("hydromodpy.display"):
                del sys.modules[mod]
        sys.modules.update(display_modules)
        # The fresh import also bound each new module on its parent package.
        # Left there, a monkeypatch target such as "hydromodpy.display.runs.x"
        # would land on an orphaned copy.
        for name, module in display_modules.items():
            parent, _, child = name.rpartition(".")
            setattr(sys.modules[parent], child, module)
        if "hydromodpy.display" not in display_modules:
            vars(sys.modules["hydromodpy"]).pop("display", None)

    after = dict(matplotlib.rcParams)
    changed = {k: (before.get(k), after.get(k)) for k in after if before.get(k) != after.get(k)}
    assert not changed, f"importing hydromodpy.display mutated rcParams: {changed}"
