"""The display package keeps no banned colormap, hardcoded EPSG or matplotlib side effect."""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

from hydromodpy.display.style import BANNED_CMAPS

# No figure hard-codes a banned colormap name.
#
# Scans every ``hydromodpy/display/figures/*.py`` and every renderer helper
# for string literals that match a banned cmap name (``jet``, ``rainbow``,
# ``hsv``, ``nipy_spectral``, ``gist_rainbow``).


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
                    # style.py declares the banned list itself.
                    if path.relative_to(repo_root).as_posix() == "hydromodpy/display/style.py":
                        continue
                    offending.append(
                        (path.relative_to(repo_root).as_posix(), node.lineno, node.value)
                    )
    assert not offending, (
        f"Display files use banned cmap literal(s): {offending}. "
        f"Use one of the perceptually-uniform alternatives instead."
    )


# Static analysis test: no hard-coded ``crs="EPSG:<int>"`` literals in code paths.
#
# Scans ``hydromodpy/display`` and ``hydromodpy/project/compare.py`` for
# ``crs=`` kwargs assigned to literal ``"EPSG:..."`` strings. Whitelist
# covers documented defaults and the geographic fallback used for Hub'Eau
# points which always come in EPSG:4326.

HMP_ROOT = Path(__file__).resolve().parents[3] / "hydromodpy"


TARGETS = ("display", "project/compare.py")


# Lines that legitimately mention an EPSG default (docstrings, fallbacks
# behind a None check, Pydantic Field defaults). The pattern below
# captures `crs="EPSG:...", `crs='EPSG:...', and `epsg=2154` kwargs.
HARDCODE_PATTERNS = (
    re.compile(r'crs\s*=\s*"EPSG:\d+"'),
    re.compile(r"crs\s*=\s*'EPSG:\d+'"),
    re.compile(r"epsg\s*=\s*\d+"),
)


# Each entry below is a (file_suffix, line_substring) pair that documents
# a legitimate use. Hits must match BOTH conditions to be skipped.
WHITELIST: tuple[tuple[str, str], ...] = (
    # _write_geotiff has crs_arg fallback after `if crs is None: crs_arg = "EPSG:2154"`.
    ("comparison/visuals_render_maps.py", 'crs_arg: str = "EPSG:2154"'),
    # Hub'Eau lon/lat fallback.
    ("display/overview/panels.py", 'src_crs = p.get("crs") or "EPSG:4326"'),
)


def _is_whitelisted(path: Path, line: str) -> bool:
    posix = path.as_posix()
    for suffix, substring in WHITELIST:
        if posix.endswith(suffix) and substring in line:
            return True
    return False


def _scan(target: Path) -> list[tuple[Path, int, str]]:
    offending: list[tuple[Path, int, str]] = []
    for path in [target] if target.is_file() else target.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Skip docstring lines (very rough: leading ``"`` or ``'`` triple).
            if stripped.startswith(('"""', "'''")):
                continue
            for pattern in HARDCODE_PATTERNS:
                if pattern.search(raw_line):
                    if _is_whitelisted(path, raw_line):
                        continue
                    offending.append((path, lineno, raw_line.rstrip()))
    return offending


def test_no_hardcoded_epsg_in_display_and_compare() -> None:
    offending: list[tuple[Path, int, str]] = []
    for sub in TARGETS:
        offending.extend(_scan(HMP_ROOT / sub))
    if offending:
        report = "\n".join(f"{path}:{lineno}: {line}" for path, lineno, line in offending)
        raise AssertionError(
            "Hard-coded EPSG literals found in display and project/compare.py:\n" + report
        )


# Importing :mod:`hydromodpy.display` must not touch matplotlib rcParams.
#
# Figures take a theme through :func:`themed` *when requested* but the package
# import itself must stay inert so that a user's interactive session does
# not get its styling silently rewritten.


def test_display_import_does_not_mutate_rcparams() -> None:
    import matplotlib

    before = dict(matplotlib.rcParams)
    display_modules = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith("hydromodpy.display")
    }

    try:
        # Force a fresh import to exercise the module-level code paths.
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
        # Left there, a later lookup by attribute (a monkeypatch target such as
        # "hydromodpy.display.runs._get_figure") lands on an orphaned copy.
        for name, module in display_modules.items():
            parent, _, child = name.rpartition(".")
            setattr(sys.modules[parent], child, module)
        if "hydromodpy.display" not in display_modules:
            vars(sys.modules["hydromodpy"]).pop("display", None)

    after = dict(matplotlib.rcParams)
    changed = {k: (before.get(k), after.get(k)) for k in after if before.get(k) != after.get(k)}
    assert not changed, (
        f"importing hydromodpy.display mutated rcParams: {changed}. "
        "Figures must opt-in through themed; imports must be inert."
    )
