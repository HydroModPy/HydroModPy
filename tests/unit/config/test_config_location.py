"""The configuration lives in ``hydromodpy.config`` and ``hydromodpy.schema`` only.

The older import paths are gone and must stay gone.
"""

from __future__ import annotations

import importlib
import sys

import pytest

REMOVED_MODULES = [
    pytest.param("hydromodpy.core.config", id="core config namespace"),
    pytest.param("hydromodpy.core.config.hydromodpy_config", id="core config module"),
    pytest.param("hydromodpy.core.config.schema_export", id="core schema export"),
]


def test_canonical_imports_match() -> None:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig as canonical_module
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig as canonical_pkg

    assert canonical_pkg is canonical_module


def test_schema_export_canonical_import_works() -> None:
    from hydromodpy.schema.config_schema import export_schema

    assert callable(export_schema)


@pytest.mark.parametrize("module_name", REMOVED_MODULES)
def test_removed_module(module_name: str) -> None:
    sys.modules.pop(module_name, None)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


def test_master_config_package_is_removed() -> None:
    import hydromodpy

    for module_name in (
        "hydromodpy.master_config",
        "hydromodpy.master_config.analysis",
        "hydromodpy.master_config.dynamic_flow_examples",
        "hydromodpy.master_config.hydromodpy_config",
    ):
        sys.modules.pop(module_name, None)

    assert "master_config" not in hydromodpy.__all__
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hydromodpy.master_config")


def test_core_config_export_is_removed() -> None:
    import hydromodpy.core as legacy_core

    legacy_core.__dict__.pop("HydroModPyConfig", None)
    assert "HydroModPyConfig" not in vars(legacy_core).get("__all__", ())
    with pytest.raises(AttributeError):
        _ = legacy_core.HydroModPyConfig
