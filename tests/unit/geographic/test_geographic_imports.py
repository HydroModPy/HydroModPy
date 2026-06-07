"""Import-regression tests for geographic modules."""

from __future__ import annotations

import importlib


def test_geographic_config_import_does_not_trigger_circular_import() -> None:
    """Synthetic geographic support should not recurse back into GeographicConfig."""

    module = importlib.import_module("hydromodpy.spatial.geographic.geographic_config")

    assert hasattr(module, "GeographicConfig")


def test_hydrographic_network_import_does_not_trigger_circular_import() -> None:
    module = importlib.import_module("hydromodpy.spatial.geographic.core.hydrographic_network")

    assert hasattr(module, "HydrographicNetwork")


def test_geographic_package_exports_hydrographic_network() -> None:
    module = importlib.import_module("hydromodpy.spatial.geographic")

    assert hasattr(module, "HydrographicNetwork")
    assert hasattr(module, "HydrographicNetworks")


def test_hydrographic_network_comparison_import_does_not_trigger_circular_import() -> None:
    module = importlib.import_module(
        "hydromodpy.spatial.geographic.core.hydrographic_network_comparison"
    )

    assert hasattr(module, "compare_hydrographic_networks")
