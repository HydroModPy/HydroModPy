"""Compatibility tests for climatic namespace migration."""

from __future__ import annotations

import importlib

import pytest


def test_root_climatic_symbol_points_to_data_manager_module() -> None:
    import hydromodpy as hm
    from hydromodpy.data_managers.climatic import Climatic

    assert hm.Climatic is Climatic


def test_legacy_watershed_climatic_module_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hydromodpy.watershed.climatic")
