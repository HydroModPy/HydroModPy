"""The hydrography variable: network loading from a source or a file, the cache and the extent.

A source answers river linework (or a raster) that is burned onto the reference
grid. The request box leaves in the CRS the source declares (degrees for the
shipped ones), and the permanent reaches are written apart. Coordinates of the
fake watershed are Lambert-93 meters.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import LineString, Point, Polygon

from hydromodpy.catchment.algorithms.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_VECTOR_FILENAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
)
from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.core.state.scratch import preprocessing_dir
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.loading.loader import DataLoader
from hydromodpy.data.loading.store import DataStore
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.source.permanence import PERMANENCE_COLUMN
from hydromodpy.data.variables.hydrography.config import HydrographyConfig
from hydromodpy.data.variables.hydrography.variable import HydrographyVariable
from tests._helpers.data_hydrography_builders import (
    WhiteboxStubBackend,
    _fake_inputs,
    _hydrography_array,
    _hydrography_raster_path,
    _hydrography_record,
    _hydrography_vector_path,
    _make_hydrography_load_result,
    _make_lines_gdf,
    _write_dummy_tif,
)

pytestmark = pytest.mark.fast

PREPROCESSING_DIR = preprocessing_dir(Path())
FETCH = "hydromodpy.data.variables.hydrography.variable.HydrographyVariable._fetch_from_source"
BACKEND = "hydromodpy.catchment.delineation.get_whitebox_backend"
FETCH_NETWORK = "hydromodpy.data.variables.hydrography.variable.fetch_network"
OSM_FETCH = "hydromodpy.data.variables.hydrography.apis.osm.fetch"
BDTOPAGE_FETCH = "hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected"


def manager(tmp_path: Path, sources: list[dict], *, index=None, data_dir=None):
    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=sources, mask_path=inputs.mask_path)
    return HydrographyVariable(
        config=cfg,
        out_path=tmp_path,
        base_raster=inputs.base_raster,
        index=index,
        data_dir=data_dir,
    )


def cached_manager(tmp_path: Path, index: CacheIndex, source: dict):
    return manager(tmp_path, [source], index=index, data_dir=tmp_path / "cache")


def cache_index(tmp_path: Path) -> CacheIndex:
    return CacheIndex(tmp_path / "cache")


def reaches(permanence: list[str] | None, *, x0: float = 350000.0) -> gpd.GeoDataFrame:
    """Parallel 1 km reaches inside the fake watershed, one per entry."""
    n = 3 if permanence is None else len(permanence)
    columns: dict[str, list[object]] = {"gid": list(range(n))}
    if permanence is not None:
        columns[PERMANENCE_COLUMN] = permanence
    return gpd.GeoDataFrame(
        columns,
        geometry=[
            LineString([(x0 + i * 100, 6750000.0), (x0 + i * 100, 6751000.0)]) for i in range(n)
        ],
        crs="EPSG:2154",
    )


def record_the_extent(monkeypatch) -> list:
    """Intercept the port call and keep the source and extent the variable built."""
    seen: list = []

    def fetch(source, extent):
        seen.append((source, extent))
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    monkeypatch.setattr(FETCH_NETWORK, fetch)
    return seen


def test_load_result_construction(tmp_path):
    result = _make_hydrography_load_result(
        array=np.zeros((10, 10)),
        raster_path=str(tmp_path / "s.tif"),
        vector_path=str(tmp_path / "s.shp"),
    )

    record = _hydrography_record(result)

    assert record.variable == HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME
    assert record.metadata["vector_path"] == str(tmp_path / "s.shp")
    assert record.metadata["raster_path"] == str(tmp_path / "s.tif")
    assert _hydrography_array(result).shape == (10, 10)


VECTOR_PATHS = [
    pytest.param(None, id="no vector"),
    pytest.param("/tmp/s.shp", id="vector path"),
]


@pytest.mark.parametrize("vector_path", VECTOR_PATHS)
def test_load_result_paths(vector_path):
    result = _make_hydrography_load_result(
        array=np.zeros((10, 10)), raster_path="/tmp/s.tif", vector_path=vector_path
    )

    assert _hydrography_vector_path(result) == vector_path
    assert _hydrography_raster_path(result) == "/tmp/s.tif"


# A polygon layer is burned as polygons, a point layer as points, never as lines.
SQUARE = Polygon([(350000, 6750000), (351000, 6750000), (351000, 6751000), (350000, 6751000)])
GEOMETRIES = [
    pytest.param(
        gpd.GeoDataFrame({"id": [1]}, geometry=[SQUARE], crs="EPSG:2154"),
        "vector_polygons_to_raster",
        id="polygons",
    ),
    pytest.param(
        gpd.GeoDataFrame(
            {"id": [1, 2]},
            geometry=[Point(350000, 6750000), Point(351000, 6751000)],
            crs="EPSG:2154",
        ),
        "vector_points_to_raster",
        id="points",
    ),
]


@pytest.mark.parametrize(("layer", "method"), GEOMETRIES)
@patch(BACKEND)
@patch(FETCH)
def test_load_burns_the_geometry_it_gets(mock_fetch, mock_backend_factory, layer, method, tmp_path):
    mock_fetch.return_value = layer
    backend = WhiteboxStubBackend()
    mock_backend_factory.return_value = backend

    result = manager(tmp_path, [{"source": "osm"}]).load()

    assert method in backend.method_names()
    assert "vector_lines_to_raster" not in backend.method_names()
    assert isinstance(result, LoadResult)


@patch(BACKEND)
@patch(FETCH)
def test_no_permanent_reach_no_file(fetch, backend_factory, tmp_path):
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = reaches(["intermittent", "dry"])

    result = manager(tmp_path, [{"source": "osm"}]).load()

    assert result.fields[0].metadata["permanent_vector_path"] is None


def test_request_box_in_source_crs(tmp_path, monkeypatch):
    # The Lambert-93 bounds of the fixture are around (300000, 6700000), so a box
    # handed over unconverted fails every bound below.
    seen = record_the_extent(monkeypatch)
    inputs = _fake_inputs(tmp_path, crs="EPSG:2154")
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
    with patch(BACKEND):
        variable = HydrographyVariable(config=cfg, out_path=tmp_path)

    variable._fetch_from_source(cfg.sources[0])

    source, extent = seen[0]
    assert extent.crs == source.extent_crs == "EPSG:4326"
    lon_min, lat_min, lon_max, lat_max = extent.bbox
    assert -3.0 < lon_min < lon_max < 0.0
    assert 47.0 < lat_min < lat_max < 50.0


def test_loader_fills_default_mask(tmp_path):
    watershed = tmp_path / "watershed.shp"
    result = SimpleNamespace(
        setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=watershed))
    )
    cfg = HydrographyConfig(sources=[{"source": "osm"}])

    DataLoader._apply_default_masks(cfg, result)

    assert cfg.mask_path == watershed


def test_loader_keeps_authored_mask(tmp_path):
    authored = tmp_path / "authored.gpkg"
    result = SimpleNamespace(
        setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=tmp_path / "ws.shp"))
    )
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=authored)

    DataLoader._apply_default_masks(cfg, result)

    assert cfg.mask_path == authored


@patch(BACKEND)
def test_raster_file_skips_vectors(mock_backend_factory, tmp_path):
    backend = MagicMock()
    mock_backend_factory.return_value = backend
    tif = tmp_path / "input_streams.tif"
    _write_dummy_tif(tif, crs="EPSG:2154")

    result = manager(tmp_path, [{"source": "file", "path": str(tif)}]).load()

    assert isinstance(result, LoadResult)
    assert _hydrography_vector_path(result) is None
    assert _hydrography_raster_path(result).endswith("streams.tif")
    assert isinstance(_hydrography_array(result), np.ndarray)
    backend.raster.vector_lines_to_raster.assert_not_called()


@patch(BACKEND)
def test_negative_raster_values_become_nan(mock_backend_factory, tmp_path):
    mock_backend_factory.return_value = MagicMock()
    tif = tmp_path / "neg_streams.tif"
    shape = (100, 100)
    data = np.ones(shape, dtype=np.float32)
    data[0, 0] = -32768
    data[10, 10] = -1
    with rasterio.open(
        str(tif),
        "w",
        driver="GTiff",
        height=shape[0],
        width=shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_bounds(300000, 6700000, 400000, 6800000, shape[1], shape[0]),
    ) as ds:
        ds.write(data, 1)

    result = manager(tmp_path, [{"source": "file", "path": str(tif)}]).load()

    assert np.any(np.isnan(_hydrography_array(result)))


@patch(OSM_FETCH)
@patch(BACKEND)
def test_force_refresh_bypasses_the_cache(mock_backend_factory, mock_osm_fetch, tmp_path):
    mock_backend_factory.return_value = MagicMock()
    mock_osm_fetch.return_value = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[LineString([(-1.5, 48.2), (-1.4, 48.3)])], crs="EPSG:4326"
    )
    tif_path = tmp_path / PREPROCESSING_DIR / "hydrography" / "streams.tif"
    tif_path.parent.mkdir(parents=True, exist_ok=True)
    _write_dummy_tif(tif_path)
    index = cache_index(tmp_path)
    source = {"source": "osm", "force_refresh": True}

    cached_manager(tmp_path, index, source).load()
    assert mock_osm_fetch.call_count == 1
    cached_manager(tmp_path, index, source).load()  # a cache row exists, it is not used

    assert mock_osm_fetch.call_count == 2


@patch(BDTOPAGE_FETCH)
@patch(BACKEND)
def test_same_box_served_from_cache(backend_factory, fetch, tmp_path):
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = reaches(["permanent"])
    index = cache_index(tmp_path)

    cached_manager(tmp_path, index, {"source": "bdtopage"}).load()
    cached_manager(tmp_path, index, {"source": "bdtopage"}).load()

    assert fetch.call_count == 1


@patch(OSM_FETCH)
@patch(BACKEND)
def test_other_question_is_a_miss(backend_factory, fetch, tmp_path):
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = reaches(None).to_crs("EPSG:4326")
    index = cache_index(tmp_path)

    cached_manager(tmp_path, index, {"source": "osm", "waterway_types": ["river"]}).load()
    cached_manager(tmp_path, index, {"source": "osm", "waterway_types": ["river"]}).load()
    assert fetch.call_count == 1
    cached_manager(tmp_path, index, {"source": "osm", "waterway_types": ["canal"]}).load()

    assert fetch.call_count == 2, "other waterway types over the same box are not the cached ones"


@patch(BDTOPAGE_FETCH)
@patch(BACKEND)
def test_older_row_is_still_served(backend_factory, fetch, tmp_path):
    backend_factory.return_value = WhiteboxStubBackend()
    index = cache_index(tmp_path)
    old = tmp_path / "cache" / "bdtopage_old.gpkg"
    old.parent.mkdir(parents=True)
    reaches(["permanent"]).to_crs("EPSG:4326").to_file(old, driver="GPKG")
    index.record(
        old,
        variable="hydrography",
        source="bdtopage",
        bbox=(0.0, 0.0, 1e7, 1e7),
        crs="EPSG:4326",
    )

    cached_manager(tmp_path, index, {"source": "bdtopage"}).load()

    assert fetch.call_count == 0


@patch(BDTOPAGE_FETCH)
@patch(BACKEND)
def test_orphan_permanent_copy_removed(backend_factory, fetch, tmp_path):
    # The cache unlinks a subsumed answer, and its permanent copy goes with it.
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = reaches(["permanent"])
    orphan = tmp_path / "cache" / "hydrography_bdtopage_permanent_0badf00d.gpkg"
    orphan.parent.mkdir(parents=True)
    reaches(["permanent"]).to_file(orphan, driver="GPKG")

    cached_manager(tmp_path, cache_index(tmp_path), {"source": "bdtopage"}).load()

    assert not orphan.exists()
    assert len(list((tmp_path / "cache").glob("hydrography_bdtopage_permanent_*.gpkg"))) == 1


def test_no_index_skips_the_cache(tmp_path):
    variable = manager(tmp_path, [{"source": "osm"}])

    assert variable._try_load_cached("osm", (-2, 47, -1, 49)) is None


def test_subsume_removes_a_smaller_box(tmp_path):
    data_dir = tmp_path / "cache"
    data_dir.mkdir()
    index = CacheIndex(data_dir)
    small_gpkg = data_dir / "small.gpkg"
    _make_lines_gdf().to_file(small_gpkg, driver="GPKG")
    index.record(
        small_gpkg,
        variable="hydrography",
        source="osm",
        bbox=(-2.0, 47.5, -1.5, 48.0),
        crs="EPSG:4326",
    )
    big_gpkg = data_dir / "big.gpkg"
    _make_lines_gdf().to_file(big_gpkg, driver="GPKG")
    big = index.record(
        big_gpkg,
        variable="hydrography",
        source="osm",
        bbox=(-3.0, 47.0, -1.0, 49.0),
        crs="EPSG:4326",
    )

    removed = index.subsume(big)

    assert removed == 1
    # Only the big row remains, and the small file left with its sidecar.
    assert index.rows(variable="hydrography") == [big]
    assert not small_gpkg.exists()
    assert not (data_dir / "small.gpkg.json").exists()


def test_a_user_file_is_never_subsumed(tmp_path):
    data_dir = tmp_path / "cache"
    data_dir.mkdir()
    user_file = data_dir / "custom.gpkg"
    _make_lines_gdf().to_file(user_file, driver="GPKG")
    index = CacheIndex(data_dir)
    with pytest.raises(DataCacheError, match="user file"):
        index.record(
            user_file,
            variable="hydrography",
            source="file",
            bbox=(-2.0, 47.5, -1.5, 48.0),
            crs="EPSG:4326",
        )
    big_gpkg = data_dir / "big.gpkg"
    _make_lines_gdf().to_file(big_gpkg, driver="GPKG")
    big = index.record(
        big_gpkg,
        variable="hydrography",
        source="osm",
        bbox=(-3.0, 47.0, -1.0, 49.0),
        crs="EPSG:4326",
    )

    assert index.subsume(big) == 0
    assert user_file.exists()


@patch("hydromodpy.data.variables.hydrography.variable.HydrographyVariable.load")
@patch(BACKEND)
def test_the_store_delegates_to_the_variable(mock_backend, mock_load, tmp_path):
    mock_load.return_value = _make_hydrography_load_result(
        raster_path="/tmp/s.tif", vector_path=None
    )
    (tmp_path / "data").mkdir()
    store = DataStore(workspace_root=tmp_path)
    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)

    result = store.load_hydrography(cfg, out_path=tmp_path, base_raster=inputs.base_raster)

    assert isinstance(result, LoadResult)
    mock_load.assert_called_once()


def test_variable_name():
    assert HydrographyVariable.VARIABLE_NAME == "hydrography"


@patch(FETCH)
def test_all_sources_empty_is_refused(mock_fetch, tmp_path):
    mock_fetch.return_value = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    with pytest.raises(ValueError, match="empty"):
        manager(tmp_path, [{"source": "osm"}]).load()


def test_the_geographic_parameter_is_refused():
    # The parameter is gone, not ignored.
    with pytest.raises(TypeError, match="geographic"):
        HydrographyVariable(config=None, out_path=".", geographic=object())


def test_missing_mask_refused(tmp_path, monkeypatch):
    record_the_extent(monkeypatch)
    cfg = HydrographyConfig(sources=[{"source": "osm"}])
    with patch(BACKEND):
        variable = HydrographyVariable(config=cfg, out_path=tmp_path)

    with pytest.raises(ValueError, match="mask_path"):
        variable._fetch_from_source(cfg.sources[0])


def test_missing_base_raster_refused(tmp_path):
    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
    with patch(BACKEND):
        variable = HydrographyVariable(config=cfg, out_path=tmp_path)

    with pytest.raises(ValueError, match="base_raster"):
        variable._rasterize(inputs.mask_path, "FID")
