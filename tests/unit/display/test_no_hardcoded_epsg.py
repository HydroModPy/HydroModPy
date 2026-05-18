"""Static analysis test: no hard-coded ``crs="EPSG:<int>"`` literals in code paths.

Scans ``hydromodpy/display`` and ``hydromodpy/analysis`` Python files for
``crs=`` kwargs assigned to literal ``"EPSG:..."`` strings. Whitelist
covers documented defaults and the geographic fallback used for Hub'Eau
points which always come in EPSG:4326.
"""

from __future__ import annotations

import re
from pathlib import Path

HMP_ROOT = Path(__file__).resolve().parents[3] / "hydromodpy"
TARGET_DIRS = ("display", "analysis")

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


def _scan(directory: Path) -> list[tuple[Path, int, str]]:
    offending: list[tuple[Path, int, str]] = []
    for path in directory.rglob("*.py"):
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


def test_no_hardcoded_epsg_in_display_and_analysis() -> None:
    offending: list[tuple[Path, int, str]] = []
    for sub in TARGET_DIRS:
        offending.extend(_scan(HMP_ROOT / sub))
    if offending:
        report = "\n".join(f"{path}:{lineno}: {line}" for path, lineno, line in offending)
        raise AssertionError("Hard-coded EPSG literals found in display/analysis:\n" + report)
