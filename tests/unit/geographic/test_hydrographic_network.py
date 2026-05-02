from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.data.variables.hydrography.result import HydrographyResult
from hydromodpy.spatial.geographic.core.derived_features import (
    GeographicBoundaryFeatures,
    GeographicDerivedFeatures,
    attach_reference_hydrographic_network,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_GENERATED_LEGACY_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HydrographicNetwork,
    HydrographicNetworks,
    canonical_feature_name_for_role,
    default_vector_filename_for_role,
    hydrographic_network_naming_contract,
    legacy_feature_name_for_role,
)
from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts


def _write_network_vector(
    path: Path,
    *,
    strahler: int | None = None,
) -> Path:
    data: dict[str, list[int]] = {"id": [1]}
    if strahler is not None:
        data["STRAHLER"] = [strahler]
    gdf = gpd.GeoDataFrame(
        data,
        geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
        crs="EPSG:2154",
    )
    gdf.to_file(path)
    return path


def _write_watershed(path: Path) -> Path:
    gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(0.0, -500.0, 1000.0, 500.0)],
        crs="EPSG:2154",
    )
    gdf.to_file(path)
    return path


def test_from_hydrography_result_builds_reference_network(tmp_path: Path):
    streams_path = _write_network_vector(tmp_path / "streams.shp", strahler=3)
    watershed_path = _write_watershed(tmp_path / "watershed.shp")

    result = HydrographyResult(
        streams=str(streams_path),
        tif_streams=str(tmp_path / "streams.tif"),
        streams_array=np.asarray([[1.0, 0.0], [np.nan, 0.0]], dtype=float),
    )

    network = HydrographicNetwork.from_hydrography_result(
        result,
        watershed_shp=watershed_path,
    )

    assert network.role == "reference"
    assert network.source_kind == "hydrography_loaded"
    assert network.has_vector is True
    assert network.vector_path == str(streams_path)
    assert "2154" in str(network.crs)
    assert network.metrics["segment_count"] == 1
    assert float(network.metrics["network_total_length_m"]) == pytest.approx(1000.0)
    assert float(network.metrics["catchment_area_km2"]) == pytest.approx(1.0)
    assert float(network.metrics["drainage_density_km_per_km2"]) == pytest.approx(1.0)
    assert float(network.metrics["max_strahler_order"]) == pytest.approx(3.0)
    assert network.metrics["stream_pixel_count"] == 1


def test_from_hydrography_result_handles_raster_only_payload(tmp_path: Path):
    result = HydrographyResult(
        streams=None,
        tif_streams=str(tmp_path / "streams.tif"),
        streams_array=np.asarray([[1.0, 0.0], [2.0, np.nan]], dtype=float),
    )

    network = HydrographicNetwork.from_hydrography_result(result)

    assert network.role == "reference"
    assert network.vector_path is None
    assert network.raster_path == str(tmp_path / "streams.tif")
    assert network.metrics["stream_pixel_count"] == 2


def test_from_river_network_products_builds_generated_network(tmp_path: Path):
    network_path = _write_network_vector(tmp_path / "river_network.shp")
    summary_path = tmp_path / "river_network_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "threshold_mode": "area_km2",
                "threshold_value": 0.5,
                "threshold_cells": 400.0,
                "stream_pixel_count": 12,
                "segment_count": 1,
                "network_total_length_m": 1000.0,
                "max_strahler_order": 4.0,
                "catchment_area_km2": 1.0,
                "drainage_density_km_per_km2": 1.0,
            }
        ),
        encoding="utf-8",
    )
    trace = RiverMeshTrace.from_geometries(
        source_kind="geographic_generated",
        crs_wkt="EPSG:2154",
        geometries=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
    )
    products = RiverNetworkProducts(
        enabled=True,
        threshold_cells=400.0,
        active_streams_tif=str(tmp_path / "river_streams.tif"),
        network_shp=str(network_path),
        network_crs="EPSG:2154",
        river_mesh_trace=trace,
        summary_json=str(summary_path),
    )

    network = HydrographicNetwork.from_river_network_products(
        products,
        watershed_shp=tmp_path / "watershed.shp",
    )

    assert network is not None
    assert network.role == "generated"
    assert network.source_kind == "geographic_generated"
    assert network.vector_path == str(network_path)
    assert network.river_mesh_trace is trace
    assert network.metrics["threshold_mode"] == "area_km2"
    assert float(network.metrics["threshold_value"]) == pytest.approx(0.5)
    assert network.metrics["stream_pixel_count"] == 12
    assert float(network.metadata["threshold_cells"]) == pytest.approx(400.0)


def test_geographic_derived_features_exposes_generated_hydrographic_network():
    network = HydrographicNetwork(
        role="generated",
        source_kind="geographic_generated",
        vector_path="river_network.shp",
    )
    features = GeographicDerivedFeatures(
        surface_topo=object(),
        boundaries=GeographicBoundaryFeatures(
            watershed_shp="watershed.shp",
            watershed_box_shp="watershed_box.shp",
            box_buff_shp="box_buff.shp",
        ),
        hydrographic_networks=HydrographicNetworks(generated=network),
    )

    assert features.generated_hydrographic_network is network


def test_geographic_derived_features_can_attach_reference_network(tmp_path: Path):
    streams_path = _write_network_vector(tmp_path / "streams.shp", strahler=2)
    watershed_path = _write_watershed(tmp_path / "watershed.shp")
    generated = HydrographicNetwork(
        role="generated",
        source_kind="geographic_generated",
        vector_path=str(tmp_path / "river_network.shp"),
    )
    features = GeographicDerivedFeatures(
        surface_topo=object(),
        boundaries=GeographicBoundaryFeatures(
            watershed_shp=str(watershed_path),
            watershed_box_shp="watershed_box.shp",
            box_buff_shp="box_buff.shp",
        ),
        hydrographic_networks=HydrographicNetworks(generated=generated),
    )

    updated = attach_reference_hydrographic_network(
        features,
        HydrographyResult(
            streams=str(streams_path),
            tif_streams=str(tmp_path / "streams.tif"),
            streams_array=np.asarray([[1.0, 0.0]], dtype=float),
        ),
    )

    assert updated is not features
    assert updated.generated_hydrographic_network is generated
    assert updated.reference_hydrographic_network is not None
    assert updated.reference_hydrographic_network.role == "reference"
    assert updated.reference_hydrographic_network.vector_path == str(streams_path)


def test_canonical_feature_names_are_role_specific():
    assert canonical_feature_name_for_role("reference") == HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME
    assert canonical_feature_name_for_role("generated") == HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME
    assert canonical_feature_name_for_role("mesh_constraint") is None
    assert legacy_feature_name_for_role("generated") == HYDROGRAPHIC_NETWORK_GENERATED_LEGACY_FEATURE_NAME
    assert default_vector_filename_for_role("reference") == "streams.shp"
    assert default_vector_filename_for_role("generated") == "river_network.shp"
    contract = hydrographic_network_naming_contract("reference")
    assert contract["canonical_feature_name"] == HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME
    assert contract["reference_raster_forcing_name"] == "hydrography_streams"
