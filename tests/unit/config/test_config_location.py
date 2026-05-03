from __future__ import annotations

import importlib
import sys

import pytest


def test_hydromodpy_config_canonical_imports_match() -> None:
    from hydromodpy.config import HydroModPyConfig as canonical_pkg
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig as canonical_module

    assert canonical_pkg is canonical_module


def test_core_hydromodpy_config_export_is_removed() -> None:
    import hydromodpy.core as legacy_core

    legacy_core.__dict__.pop("HydroModPyConfig", None)
    assert "HydroModPyConfig" not in legacy_core.__all__
    with pytest.raises(AttributeError):
        _ = legacy_core.HydroModPyConfig


def test_core_config_hydromodpy_config_export_is_removed() -> None:
    import hydromodpy.core.config as legacy_config_pkg

    legacy_config_pkg.__dict__.pop("HydroModPyConfig", None)
    assert "HydroModPyConfig" not in legacy_config_pkg.__all__
    with pytest.raises(AttributeError):
        _ = legacy_config_pkg.HydroModPyConfig


def test_legacy_hydromodpy_config_module_is_removed() -> None:
    sys.modules.pop("hydromodpy.core.config.hydromodpy_config", None)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hydromodpy.core.config.hydromodpy_config")


def test_schema_export_canonical_import_works() -> None:
    from hydromodpy.config.schema_export import export_schema

    assert callable(export_schema)


def test_legacy_schema_export_module_is_removed() -> None:
    sys.modules.pop("hydromodpy.core.config.schema_export", None)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hydromodpy.core.config.schema_export")
