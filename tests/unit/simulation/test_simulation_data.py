from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.results.run import Run
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)

from ._test_simulation_api_builders import _populate, _register, catalog

__all__ = ["catalog"]


class TestSimulationData:
    def test_parameters(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        df = sim.parameters
        # Homogeneous-only payload: simple index by param_name, no zone_id.
        assert set(df.index) == {"K", "Sy"}
        assert "value" in df.columns
        assert sim.parameters.loc["K", "value"] == pytest.approx(1.5)

    def test_metrics(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        df = sim.metrics
        assert len(df) == 2

    def test_timeseries(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        ts = sim.timeseries("head", station="P01")
        assert len(ts) == 10

    def test_timeseries_not_found(self, catalog):
        sid = _register(catalog)
        sim = Run(sid, catalog)
        with pytest.raises(KeyError):
            sim.timeseries("head", station="NOPE")

    def test_budget(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        df = sim.budget(component="recharge")
        assert len(df) == 1

    def test_mass_balance(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        df = sim.mass_balance
        assert len(df) == 1

    def test_provenance(self, catalog):
        sid = _register(catalog)
        catalog.write_provenance(sid, "dem", "dem.tif", np.ones(10))
        sim = Run(sid, catalog)
        df = sim.provenance
        assert len(df) == 1

    def test_hydrographic_network_accessor(self, catalog):
        sid = _register(catalog)
        gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, gdf)

        sim = Run(sid, catalog)
        result = sim.hydrographic_network("reference")

        assert len(result) == 1
        assert result.crs is not None
        assert sim.has_hydrographic_network("reference") is True
        assert sim.has_hydrographic_network("generated") is False
        assert sim.available_hydrographic_network_roles() == ["reference"]
        assert "hydrographic_network_reference" in sim.display_capabilities
        contract = sim.hydrographic_network_naming("reference")
        assert contract["canonical_feature_name"] == HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME
        assert contract["default_vector_filename"] == "streams.shp"

    def test_hydrographic_network_missing_role_reports_available_roles(self, catalog):
        sid = _register(catalog)
        gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, gdf)

        sim = Run(sid, catalog)
        with pytest.raises(KeyError, match="Available roles: reference"):
            sim.hydrographic_network("generated")

    def test_hydrographic_network_comparison_accessor_and_capability(self, catalog):
        sid = _register(catalog)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
            crs="EPSG:2154",
        )
        generated = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (800.0, 0.0)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME, generated
        )

        sim = Run(sid, catalog)
        comparison = sim.hydrographic_network_comparison(tolerance_m=25.0)
        metrics = sim.hydrographic_network_comparison_metrics(
            tolerance_m=25.0,
            comparison_id="demo",
        )

        assert comparison.reference_total_length_m == pytest.approx(1000.0)
        assert comparison.candidate_total_length_m == pytest.approx(800.0)
        assert metrics["comparison_id"] == "demo"
        assert metrics["reference_total_length_m"] == pytest.approx(1000.0)
        assert metrics["candidate_total_length_m"] == pytest.approx(800.0)
        assert "hydrographic_network_reference" in sim.display_capabilities
        assert "hydrographic_network_generated" in sim.display_capabilities
        assert "hydrographic_network_comparison" in sim.display_capabilities
        assert "hydrographic_network_reference_missing_only" in sim.display_capabilities
        assert "hydrographic_network_generated_extra_only" in sim.display_capabilities
        generated_contract = sim.hydrographic_network_naming("generated")
        assert (
            generated_contract["canonical_feature_name"]
            == HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME
        )
        assert set(generated_contract) == {
            "role",
            "canonical_feature_name",
            "default_vector_filename",
            "reference_raster_forcing_name",
        }

    def test_hydrographic_network_comparison_requires_both_roles(self, catalog):
        sid = _register(catalog)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference
        )

        sim = Run(sid, catalog)
        with pytest.raises(
            ValueError,
            match="requires both requested roles to be present.*Missing: generated",
        ):
            sim.hydrographic_network_comparison(tolerance_m=25.0)
