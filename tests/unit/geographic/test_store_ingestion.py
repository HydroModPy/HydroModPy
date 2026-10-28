"""What a geographic run leaves in the project store, and how its tree is dropped."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from hydromodpy.spatial.geographic import store_ingestion
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME as NETWORK,
)
from hydromodpy.spatial.geographic.geographic_config import CappedBreachConfig
from hydromodpy.spatial.geographic.store_ingestion import (
    cleanup_stable_folder,
    persist_geographic_to_store,
    read_raster_data_and_meta,
)
from hydromodpy.spatial.terrain import CappedBreach, CappedBreachReport
from tests._helpers.geographic_cases import LAMBERT, write_features
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.terrain_doubles import fake_flow_products

DEM = np.arange(12, dtype="float32").reshape(3, 4)


class _Store:
    """A project store that keeps what it is given."""

    def __init__(self) -> None:
        self.rasters: dict[str, SimpleNamespace] = {}
        self.features: dict[str, gpd.GeoDataFrame] = {}
        self.metadata: dict[str, str] = {}

    def write_geographic_raster(self, sim_id, name, data, *, transform, crs, nodata) -> None:
        self.rasters[name] = SimpleNamespace(data=data, transform=transform, crs=crs, nodata=nodata)

    def write_geographic_feature(self, sim_id, name, frame) -> None:
        self.features[name] = frame

    def write_geographic_metadata(self, sim_id, metadata) -> None:
        self.metadata.update(metadata)


def _backend(monkeypatch, backend: object = None) -> SimpleNamespace:
    backend = backend if backend is not None else SimpleNamespace()
    monkeypatch.setattr(store_ingestion, "resolve_delineation_backend", lambda: backend)
    return backend


def _persist(geographic, monkeypatch, *, backend: object = None, **kwargs) -> _Store:
    _backend(monkeypatch, backend)
    store = _Store()
    persist_geographic_to_store(geographic, store, sim_id="sim", **kwargs)
    return store


def _line(path: Path, *, crs: str | None) -> Path:
    return write_features(path, [LineString([(0, 0), (10, 0)])], crs=crs)


def test_without_a_run_id_nothing_is_written(monkeypatch) -> None:
    _backend(monkeypatch)
    store = _Store()

    persist_geographic_to_store(SimpleNamespace(crs_proj=LAMBERT), store, sim_id=None)

    assert (store.rasters, store.features, store.metadata) == ({}, {}, {})


def test_a_run_read_from_disk_reaches_the_store_and_its_tree_is_dropped(
    tmp_path, monkeypatch
) -> None:
    stable = tmp_path / "stable"
    geographic_path, correcflow = stable / "geographic", stable / "correcflow"
    correcflow.mkdir(parents=True)
    geographic_path.mkdir()
    empty = gpd.GeoDataFrame(geometry=[], crs=LAMBERT)
    empty.to_file(geographic_path / "contour.gpkg", driver="GPKG")
    geographic = SimpleNamespace(
        stable_folder=str(stable),
        geographic_path=str(geographic_path),
        correcflow_path=str(correcflow),
        watershed_dem=str(write_geotiff(geographic_path / "dem.tif", DEM, nodata=-9999.0)),
        watershed_fill=str(geographic_path / "never_written.tif"),
        watershed_shp=str(write_features(geographic_path / "ws.shp", [box(0, 0, 4, 3)])),
        box_buff=None,
        watershed_contour_shp=str(geographic_path / "contour.gpkg"),
        hydrographic_network_generated_shp=str(_line(geographic_path / "net.shp", crs=None)),
        crs_proj=LAMBERT,
        catch_area=12.5,
        x_outlet=None,
        dem_box_buff_data=DEM,
    )

    store = _persist(geographic, monkeypatch, cleanup=True)

    assert list(store.rasters) == ["watershed_dem"]
    raster = store.rasters["watershed_dem"]
    np.testing.assert_array_equal(raster.data, DEM)
    assert raster.transform == tuple(from_origin(0.0, 3.0, 1.0, 1.0))[:6]
    assert (raster.crs, raster.nodata) == (LAMBERT, -9999.0)
    assert sorted(store.features) == sorted(["watershed", NETWORK])
    assert store.features[NETWORK].crs == LAMBERT
    assert store.metadata == {"crs_proj": LAMBERT, "catch_area": "12.5", "nrow": "3", "ncol": "4"}
    assert not stable.exists()


def test_a_raster_the_backend_still_holds_is_read_from_its_cache(tmp_path, monkeypatch) -> None:
    """A cache miss falls back to the file, and a raster without nodata gets the store's."""
    cached = np.ones((2, 2), dtype="float32")
    raster_backend = SimpleNamespace(
        get_cached_raster_numpy=lambda path: cached if path == "cached.tif" else None,
        get_cached_raster_metadata=lambda path: {"transform": (1, 0, 0, 0, -1, 2), "nodata": None},
    )
    fill = write_geotiff(tmp_path / "fill.tif", DEM, nodata=None)
    geographic = SimpleNamespace(watershed_dem="cached.tif", watershed_fill=str(fill))

    store = _persist(geographic, monkeypatch, backend=SimpleNamespace(raster=raster_backend))

    assert store.rasters["watershed_dem"].data is cached
    assert store.rasters["watershed_dem"].transform == (1, 0, 0, 0, -1, 2)
    assert store.rasters["watershed_dem"].crs == ""
    assert store.rasters["watershed_fill"].data.shape == DEM.shape
    assert {raster.nodata for raster in store.rasters.values()} == {-99999.0}


def test_a_cached_raster_reads_as_the_same_raster_on_disk(tmp_path, monkeypatch) -> None:
    """The backend gives the affine transform, so the pixel height keeps its sign."""
    path = write_geotiff(tmp_path / "dem.tif", DEM, origin=(10.0, 20.0), cell=5.0, nodata=-9.0)
    _backend(monkeypatch)
    data, *on_disk = read_raster_data_and_meta(path)
    raster = SimpleNamespace(
        get_cached_raster_numpy=lambda path: DEM,
        get_cached_raster_metadata=lambda path: {
            "transform": (5.0, 0.0, 10.0, 0.0, -5.0, 20.0),
            "crs": LAMBERT,
            "nodata": -9.0,
        },
    )
    _backend(monkeypatch, SimpleNamespace(raster=raster))
    cached, *from_cache = read_raster_data_and_meta(tmp_path / "only_in_the_cache.tif")

    np.testing.assert_array_equal(data, DEM)
    assert cached is DEM
    assert on_disk == from_cache == [(5.0, 0.0, 10.0, 0.0, -5.0, 20.0), -9.0, LAMBERT]


def _broken_features():
    raise RuntimeError("no derived features on this runtime")


@pytest.mark.parametrize(
    "where",
    ["river_products", "generated_network", "derived_rivers", "epsg", "broken_features", "nowhere"],
)
def test_the_generated_network_is_found_and_given_a_crs_wherever_the_runtime_keeps_it(
    where, tmp_path, monkeypatch
) -> None:
    network = str(_line(tmp_path / "net.shp", crs=None))
    rivers = SimpleNamespace(hydrographic_network_generated_shp=network, network_crs=LAMBERT)
    derived = {
        "generated_network": SimpleNamespace(
            generated_hydrographic_network=SimpleNamespace(vector_path=network, crs=LAMBERT),
            rivers=None,
        ),
        "derived_rivers": SimpleNamespace(generated_hydrographic_network=None, rivers=rivers),
    }
    geographic = {
        "river_products": SimpleNamespace(_river_network_products=rivers),
        "epsg": SimpleNamespace(hydrographic_network_generated_shp=network, epsg=2154),
        "broken_features": SimpleNamespace(
            hydrographic_network_generated_shp=network,
            get_geographic_derived_features=_broken_features,
            crs_proj=LAMBERT,
        ),
        "nowhere": SimpleNamespace(hydrographic_network_generated_shp=network, crs_proj=""),
    }.get(where) or SimpleNamespace(get_geographic_derived_features=lambda: derived[where])

    store = _persist(geographic, monkeypatch)

    assert store.features[NETWORK].crs == (None if where == "nowhere" else LAMBERT)


def test_a_runtime_without_a_network_writes_none(tmp_path, monkeypatch) -> None:
    empty = tmp_path / "empty.gpkg"
    gpd.GeoDataFrame(geometry=[], crs=LAMBERT).to_file(empty, driver="GPKG")

    for geographic in (
        SimpleNamespace(hydrographic_network_generated_shp=str(tmp_path / "absent.shp")),
        SimpleNamespace(hydrographic_network_generated_shp=str(empty)),
        SimpleNamespace(get_geographic_derived_features=lambda: None),
    ):
        assert _persist(geographic, monkeypatch).features == {}


@pytest.mark.parametrize("method", ["fill", "capped_breach"])
def test_the_run_metadata_records_the_capped_breach_limits_and_what_they_produced(
    method, monkeypatch
) -> None:
    report = CappedBreachReport(
        cells_lowered=4,
        cells_raised=12,
        max_lowering_m=0.56,
        max_raise_m=0.2,
        max_dist_cells=8,
        max_cost_m=0.5,
        move_threshold_m=0.01,
    )
    flow_products = fake_flow_products(method=CappedBreach(0.5, 200.0))
    directions = flow_products.accumulation.directions
    directions = replace(
        directions, conditioned_dem=replace(directions.conditioned_dem, breach_report=report)
    )
    flow_products = type(flow_products)(
        accumulation=replace(flow_products.accumulation, directions=directions)
    )
    geographic = SimpleNamespace(
        dem_correc_type=method, capped_breach=None, _flow_products=flow_products
    )

    written = _persist(geographic, monkeypatch).metadata

    limits = sorted(key for key in written if key.startswith("capped_breach"))
    if method == "fill":
        assert limits == []
        return
    assert written["capped_breach_max_depth_m"] == str(CappedBreachConfig().max_depth)
    assert written["capped_breach_realised_max_lowering_m"] == "0.56"
    assert written["capped_breach_realised_cells_raised"] == "12"


def test_the_preprocessing_tree_is_dropped_with_its_empty_scratch_folders(
    tmp_path, monkeypatch
) -> None:
    cleared: list[bool] = []
    _backend(
        monkeypatch,
        SimpleNamespace(raster=SimpleNamespace(clear_raster_cache=lambda: cleared.append(True))),
    )
    scratch = tmp_path / ".hmp" / "scratch"
    stable = scratch / "run" / "_preprocessing"
    (stable / "demcorrecflow").mkdir(parents=True)
    (stable / "demcorrecflow" / "dem.tif").write_bytes(b"x" * 100)
    (stable / "watershed.json").write_bytes(b"y" * 20)
    shared = tmp_path / "shared" / "scratch" / "_preprocessing"
    shared.mkdir(parents=True)
    (shared.parent / "other_run.log").write_text("kept")

    kept = cleanup_stable_folder(SimpleNamespace(stable_folder=str(stable)), keep=True)
    freed = cleanup_stable_folder(SimpleNamespace(stable_folder=str(stable)))
    cleanup_stable_folder(SimpleNamespace(stable_folder=str(shared)))

    assert (kept, freed) == (0, 120)
    assert cleared == [True, True, True]
    assert not scratch.exists()
    assert (tmp_path / ".hmp").is_dir()
    assert not shared.exists()
    assert (shared.parent / "other_run.log").is_file()
    for absent in (None, str(tmp_path / "gone")):
        assert cleanup_stable_folder(SimpleNamespace(stable_folder=absent)) == 0
