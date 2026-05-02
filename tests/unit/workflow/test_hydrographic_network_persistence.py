from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, box

from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.data.variables.hydrography.result import HydrographyResult
from hydromodpy.spatial.geographic.core.derived_features import (
    GeographicBoundaryFeatures,
    GeographicDerivedFeatures,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HydrographicNetwork,
    HydrographicNetworks,
)
from hydromodpy.spatial.geographic.store_ingestion import persist_geographic_to_store
from hydromodpy.workflow.steps.data_loading import apply_structural_updates_from_data
from hydromodpy.workflow.steps.result_ingestion import step_persist_forcings


def _write_network_vector(path: Path, *, crs: str | None = "EPSG:2154") -> Path:
    gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
        crs=crs,
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


class _FakeZarr:
    def __init__(self) -> None:
        self.fields: list[str] = []

    def write_forcing_field(self, name, data, *, unit, source) -> None:
        _ = data, unit, source
        self.fields.append(str(name))


class _FakeStore:
    def __init__(self) -> None:
        self.zarr = _FakeZarr()
        self.feature_names: list[str] = []
        self.feature_crs: dict[str, str | None] = {}
        self.metadata: dict[str, object] = {}

    def open_zarr(self, sim_id: str):
        _ = sim_id
        return self.zarr

    def write_geographic_feature(self, sim_id: str, feature_name: str, gdf) -> None:
        _ = sim_id, gdf
        self.feature_names.append(str(feature_name))
        self.feature_crs[str(feature_name)] = None if gdf.crs is None else str(gdf.crs)

    def write_geographic_metadata(self, sim_id: str, metadata: dict[str, object]) -> None:
        _ = sim_id
        self.metadata.update(metadata)


def test_step_persist_forcings_writes_reference_network_feature(tmp_path: Path):
    streams_path = _write_network_vector(tmp_path / "streams.shp")
    watershed_path = _write_watershed(tmp_path / "watershed.shp")
    reference = HydrographicNetwork(
        role="reference",
        source_kind="hydrography_loaded",
        vector_path=str(streams_path),
        watershed_shp=str(watershed_path),
    )
    features = GeographicDerivedFeatures(
        surface_topo=object(),
        boundaries=GeographicBoundaryFeatures(
            watershed_shp=str(watershed_path),
            watershed_box_shp=None,
            box_buff_shp="box_buff.shp",
        ),
        hydrographic_networks=HydrographicNetworks(reference=reference),
    )
    ctx = SimpleNamespace(
        store=_FakeStore(),
        sim_id="sim-1",
        loaded_data=LoadedDataContext(
            hydrography=HydrographyResult(
                streams=str(streams_path),
                tif_streams=str(tmp_path / "streams.tif"),
                streams_array=np.asarray([[1.0, 0.0]], dtype=float),
            )
        ),
        setup=SimpleNamespace(geographic_features=features),
    )

    step_persist_forcings(ctx)

    assert "hydrography_streams" in ctx.store.zarr.fields
    assert HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME in ctx.store.feature_names


def test_apply_structural_updates_from_data_attaches_reference_network(
    tmp_path: Path,
    monkeypatch,
):
    streams_path = _write_network_vector(tmp_path / "streams.shp")
    watershed_path = _write_watershed(tmp_path / "watershed.shp")
    features = GeographicDerivedFeatures(
        surface_topo=object(),
        boundaries=GeographicBoundaryFeatures(
            watershed_shp=str(watershed_path),
            watershed_box_shp=None,
            box_buff_shp="box_buff.shp",
        ),
        hydrographic_networks=HydrographicNetworks(),
    )
    ctx = SimpleNamespace(
        setup=SimpleNamespace(
            domain=object(),
            flow=object(),
            time_grid=None,
            geographic_features=features,
        ),
        loaded_data=LoadedDataContext(
            hydrography=HydrographyResult(
                streams=str(streams_path),
                tif_streams=str(tmp_path / "streams.tif"),
                streams_array=np.asarray([[1.0, 0.0]], dtype=float),
            ),
        ),
        cfg=SimpleNamespace(),
    )

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_geology_to_domain",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.ensure_flow",
        lambda run_state: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_oceanic_to_flow",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_recharge_load_result_to_flow",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_etp_load_result_to_flow",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.resolve_simulation_time_window",
        lambda cfg: None,
    )

    apply_structural_updates_from_data(ctx)

    assert ctx.setup.geographic_features.reference_hydrographic_network is not None
    assert (
        ctx.setup.geographic_features.reference_hydrographic_network.vector_path
        == str(streams_path)
    )


def test_persist_geographic_to_store_writes_generated_network_canonical_name(tmp_path: Path):
    network_path = _write_network_vector(tmp_path / "river_network.shp")
    watershed_path = _write_watershed(tmp_path / "watershed.shp")
    generated = HydrographicNetwork(
        role="generated",
        source_kind="geographic_generated",
        vector_path=str(network_path),
        watershed_shp=str(watershed_path),
    )
    geographic = SimpleNamespace(
        watershed_dem=None,
        watershed_fill=None,
        watershed_shp=None,
        box_buff=None,
        watershed_contour_shp=None,
        get_geographic_derived_features=lambda: GeographicDerivedFeatures(
            surface_topo=object(),
            boundaries=GeographicBoundaryFeatures(
                watershed_shp=str(watershed_path),
                watershed_box_shp=None,
                box_buff_shp="box_buff.shp",
            ),
            hydrographic_networks=HydrographicNetworks(generated=generated),
        ),
    )
    store = _FakeStore()

    persist_geographic_to_store(geographic, store, sim_id="sim-2")

    assert "river_network" in store.feature_names
    assert HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME in store.feature_names


def test_persist_geographic_to_store_restores_generated_network_crs(tmp_path: Path):
    network_path = _write_network_vector(tmp_path / "river_network_no_crs.shp", crs=None)
    watershed_path = _write_watershed(tmp_path / "watershed.shp")
    generated = HydrographicNetwork(
        role="generated",
        source_kind="geographic_generated",
        vector_path=str(network_path),
        crs="EPSG:2154",
        watershed_shp=str(watershed_path),
    )
    geographic = SimpleNamespace(
        watershed_dem=None,
        watershed_fill=None,
        watershed_shp=None,
        box_buff=None,
        watershed_contour_shp=None,
        get_geographic_derived_features=lambda: GeographicDerivedFeatures(
            surface_topo=object(),
            boundaries=GeographicBoundaryFeatures(
                watershed_shp=str(watershed_path),
                watershed_box_shp=None,
                box_buff_shp="box_buff.shp",
            ),
            hydrographic_networks=HydrographicNetworks(generated=generated),
        ),
    )
    store = _FakeStore()

    persist_geographic_to_store(geographic, store, sim_id="sim-3")

    assert store.feature_crs["river_network"] == "EPSG:2154"
    assert store.feature_crs[HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME] == "EPSG:2154"
