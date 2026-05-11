from __future__ import annotations

from pathlib import Path

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
    Path("tests/unit/config/test_config_location.py").resolve(),
    Path(__file__).resolve(),
}


SEARCH_ROOTS = (
    Path("hydromodpy"),
    Path("tests"),
    Path("docs/source"),
)


def test_sources_use_canonical_config_imports() -> None:
    offenders: list[str] = []
    for root in SEARCH_ROOTS:
        for path in root.rglob("*"):
            if path.resolve() in EXCLUDED_PATHS or not path.is_file():
                continue
            if path.suffix not in {".py", ".rst", ".md"}:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_CONFIG_IMPORTS:
                if pattern in text:
                    offenders.append(f"{path}: {pattern}")

    assert not offenders, (
        "Source files should import HydroModPyConfig and schema export from "
        "hydromodpy.config, not from compatibility aliases:\n" + "\n".join(offenders)
    )


def test_hydromodpy_package_uses_canonical_config_imports() -> None:
    offenders: list[str] = []
    for path in Path("hydromodpy").rglob("*.py"):
        if path.resolve() in EXCLUDED_PATHS:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_CONFIG_IMPORTS:
            if pattern in text:
                offenders.append(f"{path}: {pattern}")

    assert not offenders, (
        "Production code should import HydroModPyConfig and schema export from "
        "hydromodpy.config, not from compatibility aliases:\n" + "\n".join(offenders)
    )
