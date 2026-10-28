"""The geographic modules import without a cycle, and the package facade is lazy."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("hydromodpy.spatial.geographic.geographic_config", "GeographicConfig"),
        ("hydromodpy.spatial.geographic.core.hydrographic_network", "HydrographicNetwork"),
        (
            "hydromodpy.spatial.geographic.core.hydrographic_network_comparison",
            "compare_hydrographic_networks",
        ),
        ("hydromodpy.spatial.geographic", "HydrographicNetwork"),
        ("hydromodpy.spatial.geographic", "HydrographicNetworks"),
        ("hydromodpy.spatial.geographic.synthetic", "build_synthetic_geographic"),
    ],
)
def test_a_geographic_name_imports_without_a_cycle(module: str, name: str) -> None:
    """Synthetic geographic support must not recurse back into GeographicConfig."""
    assert getattr(importlib.import_module(module), name) is not None


@pytest.mark.parametrize(
    "package", ["hydromodpy.spatial.geographic", "hydromodpy.spatial.geographic.synthetic"]
)
def test_a_name_the_facade_does_not_export_is_an_attribute_error(package: str) -> None:
    with pytest.raises(AttributeError, match="no_such_name"):
        _ = importlib.import_module(package).no_such_name
