"""The stream network a run stores under two roles, reference and generated.

Lengths are in m. A role is present when its feature was written to the run, and
the comparison needs both.
"""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.catchment.algorithms.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)
from hydromodpy.results.run.view import Run
from tests._helpers.run_builders import runs

__all__ = ["runs"]


def line_of(length_m: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id": [1]}, geometry=[LineString([(0.0, 0.0), (length_m, 0.0)])], crs="EPSG:2154"
    )


def run_with_networks(runs, **lengths_m):
    """A run holding the roles named in ``lengths_m`` (reference, generated)."""
    store = runs.open()
    names = {
        "reference": HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
        "generated": HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    }
    for role, length_m in lengths_m.items():
        store.write_geographic_feature(store.sim_id, names[role], line_of(length_m))
    return Run(store.sim_id, runs.catalog())


def test_reference_network_accessor(runs):
    sim = run_with_networks(runs, reference=1.0)

    result = sim.hydrographic_network("reference")

    assert len(result) == 1
    assert result.crs is not None
    assert sim.has_hydrographic_network("reference") is True
    assert sim.has_hydrographic_network("generated") is False
    assert sim.available_hydrographic_network_roles() == ["reference"]
    contract = sim.hydrographic_network_naming("reference")
    assert contract["canonical_feature_name"] == HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME
    assert contract["default_vector_filename"] == "streams.shp"


def test_comparison_of_the_two_roles(runs):
    sim = run_with_networks(runs, reference=1000.0, generated=800.0)

    comparison = sim.hydrographic_network_comparison(tolerance_m=25.0)
    metrics = sim.hydrographic_network_comparison_metrics(tolerance_m=25.0, comparison_id="demo")

    assert comparison.reference_total_length_m == pytest.approx(1000.0)
    assert comparison.candidate_total_length_m == pytest.approx(800.0)
    assert metrics["comparison_id"] == "demo"
    assert metrics["reference_total_length_m"] == pytest.approx(1000.0)
    assert metrics["candidate_total_length_m"] == pytest.approx(800.0)
    generated_contract = sim.hydrographic_network_naming("generated")
    assert (
        generated_contract["canonical_feature_name"] == HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME
    )
    assert set(generated_contract) == {
        "role",
        "canonical_feature_name",
        "default_vector_filename",
        "reference_raster_forcing_name",
    }


def test_a_missing_role_names_the_available_ones(runs):
    sim = run_with_networks(runs, reference=1000.0)

    with pytest.raises(KeyError, match="Available roles: reference"):
        sim.hydrographic_network("generated")


def test_the_comparison_needs_both_roles(runs):
    sim = run_with_networks(runs, reference=1000.0)

    with pytest.raises(
        ValueError, match="requires both requested roles to be present.*Missing: generated"
    ):
        sim.hydrographic_network_comparison(tolerance_m=25.0)
