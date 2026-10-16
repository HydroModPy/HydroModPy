from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.display import get as get_figure
from hydromodpy.results.run import Run
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
)

from ._test_simulation_api_builders import populate, runs

__all__ = ["runs"]


class TestSimulationData:
    def test_parameters(self, runs):
        store = runs.open()
        populate(store)
        sim = Run(store.sim_id, runs.catalog())
        df = sim.parameters
        # Homogeneous-only payload: simple index by param_name, no zone_id.
        assert set(df.index) == {"K", "Sy"}
        assert "value" in df.columns
        assert sim.parameters.loc["K", "value"] == pytest.approx(1.5)

    def test_metrics(self, runs):
        store = runs.open()
        populate(store)
        sim = Run(store.sim_id, runs.catalog())
        assert set(sim.metrics["metric"]) == {"nse", "kge"}

    def test_timeseries(self, runs):
        store = runs.open()
        populate(store)
        sim = Run(store.sim_id, runs.catalog())
        ts = sim.timeseries("head", station="P01")
        assert len(ts) == 10

    def test_timeseries_not_found(self, runs):
        sim = Run(runs.open().sim_id, runs.catalog())
        with pytest.raises(KeyError):
            sim.timeseries("head", station="NOPE")

    def test_budget(self, runs):
        store = runs.open()
        populate(store)
        sim = Run(store.sim_id, runs.catalog())
        df = sim.budget(component="recharge")
        assert len(df) == 1

    def test_mass_balance(self, runs):
        store = runs.open()
        populate(store)
        sim = Run(store.sim_id, runs.catalog())
        df = sim.mass_balance
        assert len(df) == 1

    def test_hydrographic_network_accessor(self, runs):
        store = runs.open()
        sid = store.sim_id
        gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])],
            crs="EPSG:2154",
        )
        store.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, gdf)

        sim = Run(sid, runs.catalog())
        result = sim.hydrographic_network("reference")

        assert len(result) == 1
        assert result.crs is not None
        assert sim.has_hydrographic_network("reference") is True
        assert sim.has_hydrographic_network("generated") is False
        assert sim.available_hydrographic_network_roles() == ["reference"]
        assert get_figure("hydrographic_network_reference").unavailable_reason(sim) is None
        contract = sim.hydrographic_network_naming("reference")
        assert contract["canonical_feature_name"] == HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME
        assert contract["default_vector_filename"] == "streams.shp"

    def test_the_permanent_network_is_read_back_by_its_role(self, runs):
        store = runs.open()
        sid = store.sim_id
        gdf = gpd.GeoDataFrame(
            {"permanence": ["permanent"]},
            geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])],
            crs="EPSG:2154",
        )
        store.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, gdf)
        store.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME, gdf
        )

        sim = Run(sid, runs.catalog())

        assert sim.available_hydrographic_network_roles() == ["reference", "reference_permanent"]
        assert len(sim.hydrographic_network("reference_permanent")) == 1

    def test_hydrographic_network_missing_role_reports_available_roles(self, runs):
        store = runs.open()
        sid = store.sim_id
        gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])],
            crs="EPSG:2154",
        )
        store.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, gdf)

        sim = Run(sid, runs.catalog())
        with pytest.raises(KeyError, match="Available roles: reference"):
            sim.hydrographic_network("generated")

    def test_hydrographic_network_comparison_accessor_and_capability(self, runs):
        store = runs.open()
        sid = store.sim_id
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
        store.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference)
        store.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME, generated)

        sim = Run(sid, runs.catalog())
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
        assert get_figure("hydrographic_network_reference").unavailable_reason(sim) is None
        assert get_figure("hydrographic_network_generated").unavailable_reason(sim) is None
        assert get_figure("hydrographic_network_comparison").unavailable_reason(sim) is None
        assert (
            get_figure("hydrographic_network_reference_missing_only").unavailable_reason(sim)
            is None
        )
        assert (
            get_figure("hydrographic_network_generated_extra_only").unavailable_reason(sim) is None
        )
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

    def test_hydrographic_network_comparison_requires_both_roles(self, runs):
        store = runs.open()
        sid = store.sim_id
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
            crs="EPSG:2154",
        )
        store.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference)

        sim = Run(sid, runs.catalog())
        with pytest.raises(
            ValueError,
            match="requires both requested roles to be present.*Missing: generated",
        ):
            sim.hydrographic_network_comparison(tolerance_m=25.0)
