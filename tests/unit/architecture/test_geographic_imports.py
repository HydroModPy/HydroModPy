"""The geographic modules import without a cycle."""

import importlib

import pytest


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("hydromodpy.catchment.preprocess.geographic_config", "GeographicConfig"),
        ("hydromodpy.catchment.algorithms.hydrographic_network", "HydrographicNetwork"),
        (
            "hydromodpy.catchment.algorithms.hydrographic_network_comparison",
            "compare_hydrographic_networks",
        ),
        ("hydromodpy.catchment.synthetic.catchment", "build_synthetic_geographic"),
    ],
)
def test_a_geographic_name_imports_without_a_cycle(module: str, name: str) -> None:
    """Synthetic geographic support must not recurse back into GeographicConfig."""
    assert getattr(importlib.import_module(module), name) is not None
