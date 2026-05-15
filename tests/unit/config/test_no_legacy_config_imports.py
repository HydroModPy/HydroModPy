from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

FORBIDDEN_CONFIG_IMPORTS = (
    "from hydromodpy.core import HydroModPyConfig",
    "from hydromodpy.core.config import HydroModPyConfig",
    "hydromodpy.core.config.hydromodpy_config",
    "hydromodpy.core.config.schema_export",
    "from hydromodpy.master_config",
    "import hydromodpy.master_config",
    "hydromodpy.master_config",
    ":class:`~hydromodpy.core.config.HydroModPyConfig",
    ":class:`hydromodpy.core.config.HydroModPyConfig",
    "hydromodpy.core.config.HydroModPyConfig",
)

EXCLUDED_PATHS = {
    Path("tests/unit/config/test_config_location.py"),
    Path("tests/unit/config/test_no_legacy_config_imports.py"),
}


SEARCH_ROOTS = (
    ROOT / "hydromodpy",
    ROOT / "tests",
    ROOT / "docs/source",
)


def _iter_source_files(root: Path) -> Iterator[Path]:
    pruned_dirs = {"__pycache__", ".pytest_cache", "_static"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in pruned_dirs]
        base = Path(dirpath)
        for filename in filenames:
            path = base / filename
            if path.suffix in {".py", ".rst", ".md"}:
                yield path


def test_sources_use_canonical_config_imports() -> None:
    offenders: list[str] = []
    for root in SEARCH_ROOTS:
        for path in _iter_source_files(root):
            if not path.is_file():
                continue
            rel_path = path.relative_to(ROOT)
            if rel_path in EXCLUDED_PATHS:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_CONFIG_IMPORTS:
                if pattern in text:
                    offenders.append(f"{rel_path}: {pattern}")

    assert not offenders, (
        "Source files should import HydroModPyConfig and schema export from "
        "hydromodpy.config, not from compatibility aliases:\n" + "\n".join(offenders)
    )


def test_hydromodpy_package_uses_canonical_config_imports() -> None:
    offenders: list[str] = []
    for path in (ROOT / "hydromodpy").rglob("*.py"):
        rel_path = path.relative_to(ROOT)
        if rel_path in EXCLUDED_PATHS:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_CONFIG_IMPORTS:
            if pattern in text:
                offenders.append(f"{rel_path}: {pattern}")

    assert not offenders, (
        "Production code should import HydroModPyConfig and schema export from "
        "hydromodpy.config, not from compatibility aliases:\n" + "\n".join(offenders)
    )
