"""What a geographic run leaves in the project store, and how its tree is dropped."""

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from hydromodpy.catchment.algorithms.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME as NETWORK,
)
from hydromodpy.catchment.preprocess.capped_breach_config import CappedBreachConfig
from hydromodpy.catchment.preprocess.preprocessing_cleanup import cleanup_stable_folder
from hydromodpy.catchment.preprocess.store_ingestion import (
    persist_geographic_to_store,
    read_raster_data_and_meta,
)
from hydromodpy.core.fields.nodata import RASTER_NODATA
from tests._helpers.geographic_cases import LAMBERT, capped_breach_flow_products, write_features
from tests._helpers.geotiffs import write_geotiff

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


def _persist(geographic, **kwargs) -> _Store:
    store = _Store()
    persist_geographic_to_store(geographic, store, sim_id="sim", **kwargs)
    return store


def _line(path: Path, *, crs: str | None) -> Path:
    return write_features(path, [LineString([(0, 0), (10, 0)])], crs=crs)


def test_a_run_read_from_disk_reaches_the_store_and_its_tree_is_dropped(tmp_path) -> None:
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
    store = _persist(geographic, cleanup=True)
    assert list(store.rasters) == ["watershed_dem"]
    raster = store.rasters["watershed_dem"]
    np.testing.assert_array_equal(raster.data, DEM)
    assert raster.transform == tuple(from_origin(0.0, 3.0, 1.0, 1.0))[:6]
    assert (raster.crs, raster.nodata) == (LAMBERT, -9999.0)
    assert sorted(store.features) == sorted(["watershed", NETWORK])
    assert store.features[NETWORK].crs == LAMBERT
    assert store.metadata == {"crs_proj": LAMBERT, "catch_area": "12.5", "nrow": "3", "ncol": "4"}
    assert not stable.exists()


def test_a_raster_that_declares_no_nodata_lands_with_the_nodata_of_the_dem(tmp_path) -> None:
    """One sentinel for the geographic group, the -9999 the DEM beside it carries."""
    dem = write_geotiff(tmp_path / "dem.tif", DEM, origin=(10.0, 20.0), cell=5.0, nodata=-9999.0)
    fill = write_geotiff(tmp_path / "fill.tif", DEM, nodata=None)
    store = _persist(SimpleNamespace(watershed_dem=str(dem), watershed_fill=str(fill)))
    assert {raster.nodata for raster in store.rasters.values()} == {RASTER_NODATA}
    data, *meta = read_raster_data_and_meta(dem)
    np.testing.assert_array_equal(data, DEM)
    assert meta == [(5.0, 0.0, 10.0, 0.0, -5.0, 20.0), RASTER_NODATA, LAMBERT]


def _broken_features():
    raise RuntimeError("no derived features on this runtime")


@pytest.mark.parametrize(
    "where",
    ["river_products", "generated_network", "derived_rivers", "epsg", "broken_features", "nowhere"],
)
def test_the_generated_network_is_found_and_given_a_crs_wherever_the_runtime_keeps_it(
    where, tmp_path
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
    store = _persist(geographic)
    assert store.features[NETWORK].crs == (None if where == "nowhere" else LAMBERT)


def test_a_runtime_without_a_network_writes_none_and_without_a_run_id_nothing(tmp_path) -> None:
    empty = tmp_path / "empty.gpkg"
    gpd.GeoDataFrame(geometry=[], crs=LAMBERT).to_file(empty, driver="GPKG")
    for geographic in (
        SimpleNamespace(hydrographic_network_generated_shp=str(tmp_path / "absent.shp")),
        SimpleNamespace(hydrographic_network_generated_shp=str(empty)),
        SimpleNamespace(get_geographic_derived_features=lambda: None),
    ):
        assert _persist(geographic).features == {}
    store = _Store()
    persist_geographic_to_store(SimpleNamespace(crs_proj=LAMBERT), store, sim_id=None)
    assert (store.rasters, store.features, store.metadata) == ({}, {}, {})


@pytest.mark.parametrize("method", ["fill", "capped_breach"])
def test_the_run_metadata_records_the_capped_breach_limits_and_what_they_produced(method) -> None:
    geographic = SimpleNamespace(
        dem_correc_type=method, capped_breach=None, _flow_products=capped_breach_flow_products()
    )
    written = _persist(geographic).metadata
    limits = sorted(key for key in written if key.startswith("capped_breach"))
    if method == "fill":
        assert limits == []
        return
    assert written["capped_breach_max_depth_m"] == str(CappedBreachConfig().max_depth)
    assert written["capped_breach_realised_max_lowering_m"] == "0.56"
    assert written["capped_breach_realised_cells_raised"] == "12"


def test_the_preprocessing_tree_is_dropped_with_its_empty_scratch_folders(tmp_path) -> None:
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
    assert not scratch.exists()
    assert (tmp_path / ".hmp").is_dir()
    assert not shared.exists()
    assert (shared.parent / "other_run.log").is_file()
    for absent in (None, str(tmp_path / "gone")):
        assert cleanup_stable_folder(SimpleNamespace(stable_folder=absent)) == 0
