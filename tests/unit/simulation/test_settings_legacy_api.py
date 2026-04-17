"""Compatibility checks for the preserved watershed settings payload."""

from __future__ import annotations

import importlib
import sys
import warnings

import hydromodpy.watershed as watershed_root
from hydromodpy.watershed.settings import Settings as WatershedSettings


def test_watershed_settings_remain_the_canonical_legacy_settings_path() -> None:
    settings = WatershedSettings()

    settings.update_model_name("legacy_demo")
    settings.update_box_model(False)

    assert settings.model_name == "legacy_demo"
    assert settings.box is False
    assert watershed_root.Settings is WatershedSettings


def test_simulation_settings_reexports_watershed_settings_with_deprecation() -> None:
    module_name = "hydromodpy.simulation.settings"
    sys.modules.pop(module_name, None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        legacy_module = importlib.import_module(module_name)

    assert legacy_module.Settings is WatershedSettings
    assert len(caught) == 1
    assert issubclass(caught[0].category, DeprecationWarning)
    assert "hydromodpy.watershed.settings" in str(caught[0].message)
