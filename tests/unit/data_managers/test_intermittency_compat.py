"""Compatibility tests for intermittency namespace cleanup."""

from __future__ import annotations

import pytest


def test_root_intermittency_symbol_points_to_data_manager_module() -> None:
    import hydromodpy as hm
    from hydromodpy.data_managers.intermittency import Intermittency

    assert hm.Intermittency is Intermittency


def test_legacy_watershed_intermittency_module_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        import hydromodpy.watershed.intermittency  # noqa: F401
