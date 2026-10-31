"""The geographic modules import without a cycle."""

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
        ("hydromodpy.spatial.geographic.synthetic.catchment", "build_synthetic_geographic"),
    ],
)
def test_a_geographic_name_imports_without_a_cycle(module: str, name: str) -> None:
    """Synthetic geographic support must not recurse back into GeographicConfig."""
    assert getattr(importlib.import_module(module), name) is not None
