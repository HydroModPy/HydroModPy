"""One contract for the reference, generated and permanent networks, and their meters.

The permanent part of the mapped network travels under its own role,
``reference_permanent`` beside ``reference``, so a consumer picks the role
without learning which provider said which reach flows all year.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import xarray as xr
from shapely.geometry import LineString, box

from hydromodpy.catchment.algorithms.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
    HydrographicNetwork,
    canonical_feature_name_for_role,
    default_vector_filename_for_role,
    hydrographic_network_naming_contract,
)
from hydromodpy.catchment.algorithms.river_mesh_trace import RiverMeshTrace
from hydromodpy.catchment.algorithms.river_network import RiverNetworkProducts
from hydromodpy.data.contracts.load_result import LoadResult
from tests._helpers.geographic_cases import hydrography_load_result, write_features, write_lines

FIELD = HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME
KM_LINE = LineString([(0.0, 0.0), (1000.0, 0.0)])
lift = HydrographicNetwork.from_hydrography_load_result


def test_reference_network_metrics(tmp_path: Path) -> None:
    streams = write_lines(tmp_path / "streams.shp", STRAHLER=[3])
    watershed = write_features(tmp_path / "watershed.shp", [box(0.0, -500.0, 1000.0, 500.0)])
    raster = tmp_path / "streams.tif"
    result = hydrography_load_result([[1, 0], [np.nan, 0]], vector_path=streams, raster_path=raster)
    raster_only = hydrography_load_result([[1.0, 0.0], [2.0, np.nan]], raster_path=raster)
    network = lift(result, watershed_shp=watershed)
    on_raster = lift(raster_only)
    assert (network.role, network.source_kind) == ("reference", "hydrography_loaded")
    assert (network.has_vector, network.has_raster) == (True, False)
    assert network.vector_path == str(streams)
    assert "2154" in str(network.crs)
    assert network.canonical_feature_name == HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME
    assert len(network.read_vector()) == 1
    metrics = network.metrics
    assert (metrics["segment_count"], metrics["stream_pixel_count"]) == (1, 1)
    assert float(metrics["network_total_length_m"]) == pytest.approx(1000.0)
    assert float(metrics["catchment_area_km2"]) == pytest.approx(1.0)
    assert float(metrics["drainage_density_km_per_km2"]) == pytest.approx(1.0)
    assert float(metrics["max_strahler_order"]) == pytest.approx(3.0)
    # A raster-only reference counts its stream pixels.
    assert on_raster.vector_path is None
    assert on_raster.read_vector() is None
    assert on_raster.raster_path == str(raster)
    assert on_raster.metrics["stream_pixel_count"] == 2


def _record(data, metadata=None) -> SimpleNamespace:
    return SimpleNamespace(
        fields=[SimpleNamespace(variable=FIELD, data=data, metadata=metadata, crs="")]
    )


@pytest.mark.parametrize(
    ("result", "count"),
    [
        (_record(xr.Dataset({"other": (("y", "x"), [[1.0, 1.0]])})), 2),
        (_record(xr.Dataset()), None),
        (_record(SimpleNamespace(values=np.ones((3, 1)))), 3),
        (_record(SimpleNamespace(values=np.ones((0, 0))), metadata=[]), 0),
        (_record(None), None),
    ],
    ids=["first variable", "no variable", "array values", "empty array", "no data"],
)
def test_stream_pixel_count(result, count) -> None:
    network = lift(result)
    assert network.metrics.get("stream_pixel_count") == count
    assert network.crs is None


def test_refused_load_result() -> None:
    with pytest.raises(ValueError, match=FIELD):
        lift(LoadResult())


@pytest.mark.parametrize("watershed", ["gone.shp", "empty.shp"])
def test_unreadable_watershed(tmp_path, watershed) -> None:
    streams = write_lines(tmp_path / "streams.shp")
    if watershed == "empty.shp":
        write_features(tmp_path / watershed, [])
    empty_vector = write_features(tmp_path / "none.shp", [])
    network = lift(hydrography_load_result(vector_path=streams), watershed_shp=tmp_path / watershed)
    empty = lift(hydrography_load_result(vector_path=empty_vector))
    assert "catchment_area_km2" not in network.metrics
    assert network.metrics["network_total_length_m"] == pytest.approx(1000.0)
    assert empty.metrics["segment_count"] == 0


@pytest.mark.parametrize("permanent", ["streams_permanent.shp", None, "gone.shp"])
def test_permanent_network(tmp_path, permanent):
    """Never the full network under this role: that would be a wrong answer."""
    full = write_lines(tmp_path / "streams.shp", 3)
    named = None if permanent is None else tmp_path / permanent
    if permanent == "streams_permanent.shp":
        write_lines(named, 1)
    result = hydrography_load_result(vector_path=full, permanent_vector_path=named)
    network = HydrographicNetwork.permanent_from_hydrography_load_result(result)
    if permanent != "streams_permanent.shp":
        assert network is None
    else:
        assert (network.role, network.vector_path) == ("reference_permanent", str(named))
        assert network.crs == "EPSG:2154"
        assert network.metrics["network_total_length_m"] == pytest.approx(1000.0)


def test_generated_network_metrics(tmp_path):
    network_path = write_lines(tmp_path / "river_network.shp")
    summary = tmp_path / "river_network_summary.json"
    record = {"threshold_mode": "area_km2", "threshold_value": 0.5, "stream_pixel_count": 12}
    summary.write_text(json.dumps({**record, "max_strahler_order": None, "per_link": [1, 2]}))
    trace = RiverMeshTrace.from_geometries(
        source_kind="geographic_generated", crs_wkt="EPSG:2154", geometries=[KM_LINE]
    )
    products = RiverNetworkProducts(
        enabled=True,
        threshold_cells=400.0,
        active_streams_tif=str(tmp_path / "river_streams.tif"),
        hydrographic_network_generated_shp=str(network_path),
        network_crs="EPSG:2154",
        river_mesh_trace=trace,
        hydrographic_network_generated_summary_json=str(summary),
    )
    bare = RiverNetworkProducts(
        enabled=True, hydrographic_network_generated_shp=str(write_lines(tmp_path / "rn.shp", 2))
    )
    network = HydrographicNetwork.from_river_network_products(
        products, watershed_shp=tmp_path / "watershed.shp"
    )
    assert (network.role, network.source_kind) == ("generated", "geographic_generated")
    assert network.vector_path == str(network_path)
    assert network.river_mesh_trace is trace
    assert network.metrics["threshold_mode"] == "area_km2"
    assert float(network.metrics["threshold_value"]) == pytest.approx(0.5)
    assert network.metrics["stream_pixel_count"] == 12
    assert network.metrics["max_strahler_order"] is None
    assert "per_link" not in network.metrics
    assert float(network.metadata["threshold_cells"]) == pytest.approx(400.0)
    assert HydrographicNetwork.from_river_network_products(bare).metrics["segment_count"] == 2
    assert HydrographicNetwork.from_river_network_products(RiverNetworkProducts(False)) is None


@pytest.mark.parametrize(
    ("role", "feature", "filename"),
    [
        ("reference", HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, "streams.shp"),
        ("generated", HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME, "river_network.shp"),
        (
            "reference_permanent",
            HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
            "streams_permanent.shp",
        ),
        ("mesh_constraint", None, None),
    ],
)
def test_role_names(role, feature, filename) -> None:
    assert canonical_feature_name_for_role(role) == feature
    assert default_vector_filename_for_role(role) == filename
    contract = hydrographic_network_naming_contract(role)
    assert contract["canonical_feature_name"] == feature
    assert contract["reference_raster_forcing_name"] == (
        "hydrography_streams" if role == "reference" else None
    )


@pytest.mark.parametrize(
    ("members", "reason"),
    [({"role": "drawn"}, "role must be one of"), ({"source_kind": "  "}, "cannot be empty")],
)
def test_refused_role_or_source(members, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        HydrographicNetwork(**{"role": "reference", "source_kind": "file", **members})
