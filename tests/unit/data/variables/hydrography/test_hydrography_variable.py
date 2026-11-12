"""The hydrography variable: loading, the permanent network and the extent seam."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon

from hydromodpy.catchment.algorithms.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_VECTOR_FILENAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
)
from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.core.state.scratch import preprocessing_dir
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.loading.loader import DataLoader
from hydromodpy.data.source.permanence import PERMANENCE_COLUMN
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)
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

PREPROCESSING_DIR = preprocessing_dir(Path())


@pytest.mark.fast
class TestHydrographyLoadResult:
    def test_construction(self, tmp_path):
        arr = np.zeros((10, 10))
        result = _make_hydrography_load_result(
            array=arr,
            raster_path=str(tmp_path / "s.tif"),
            vector_path=str(tmp_path / "s.shp"),
        )
        record = _hydrography_record(result)
        assert record.variable == HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME
        assert record.metadata["vector_path"] == str(tmp_path / "s.shp")
        assert record.metadata["raster_path"] == str(tmp_path / "s.tif")
        assert _hydrography_array(result).shape == (10, 10)


@pytest.mark.fast
class TestCustomLoader:
    def _write_shp(self, path: Path, gdf=None):
        if gdf is None:
            gdf = _make_lines_gdf()
        path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(path)
        return path

    def test_directory_auto_detection(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_file

        subdir = tmp_path / "data"
        subdir.mkdir()
        self._write_shp(subdir / "streams.shp")
        cfg = HydrographySourceConfig(source="file", path=subdir)
        gdf = load_file(cfg)
        assert not gdf.empty

    def test_directory_empty_raises(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_file

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        cfg = HydrographySourceConfig(source="file", path=empty_dir)
        with pytest.raises(FileNotFoundError, match="No vector or raster file"):
            load_file(cfg)


@pytest.mark.fast
class TestHydrographyVariable:
    def _make_manager(self, tmp_path, sources, crs="EPSG:2154"):
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        inputs = _fake_inputs(tmp_path, crs=crs)
        cfg = HydrographyConfig(sources=sources, mask_path=inputs.mask_path)
        return HydrographyVariable(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

    @patch("hydromodpy.data.variables.hydrography.variable.HydrographyVariable._fetch_from_source")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_load_pipeline_polygon_geometry(self, mock_backend_factory, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        poly_gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[
                Polygon(
                    [
                        (350000, 6750000),
                        (351000, 6750000),
                        (351000, 6751000),
                        (350000, 6751000),
                    ]
                )
            ],
            crs="EPSG:2154",
        )
        mock_fetch.return_value = poly_gdf

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyVariable(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        result = mgr.load()
        method_names = backend.method_names()
        assert "vector_polygons_to_raster" in method_names
        assert "vector_lines_to_raster" not in method_names
        assert isinstance(result, LoadResult)

    @patch("hydromodpy.data.variables.hydrography.variable.HydrographyVariable._fetch_from_source")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_load_pipeline_point_geometry(self, mock_backend_factory, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        pt_gdf = gpd.GeoDataFrame(
            {"id": [1, 2]},
            geometry=[Point(350000, 6750000), Point(351000, 6751000)],
            crs="EPSG:2154",
        )
        mock_fetch.return_value = pt_gdf

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyVariable(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        result = mgr.load()
        method_names = backend.method_names()
        assert "vector_points_to_raster" in method_names
        assert "vector_lines_to_raster" not in method_names
        assert isinstance(result, LoadResult)

    @patch("hydromodpy.data.variables.hydrography.variable.HydrographyVariable._fetch_from_source")
    def test_all_sources_empty_raises(self, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        mock_fetch.return_value = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyVariable(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        with pytest.raises(ValueError, match="empty"):
            mgr.load()

    def test_the_request_extent_is_reprojected_for_the_source(self, tmp_path, monkeypatch):
        import geopandas as gpd

        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        seen = []

        def _fetch(source, extent):
            seen.append(extent)
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

        monkeypatch.setattr(
            "hydromodpy.data.variables.hydrography.variable.fetch_network",
            _fetch,
        )
        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyVariable(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        mgr._fetch_from_source(cfg.sources[0])

        lon_min, lat_min, lon_max, lat_max = seen[0].bbox
        # Roughly France area after reprojection from EPSG:2154
        assert -10 < lon_min < lon_max < 15
        assert 40 < lat_min < lat_max < 55


@pytest.mark.fast
class TestCustomLoaderTif:
    """TIF files should be returned as Path, not GeoDataFrame."""

    def test_tif_in_directory(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_file

        subdir = tmp_path / "data"
        subdir.mkdir()
        tif = subdir / "streams.tif"
        _write_dummy_tif(tif)
        cfg = HydrographySourceConfig(source="file", path=subdir)
        result = load_file(cfg)
        assert isinstance(result, Path)
        assert result.suffix == ".tif"

    def test_vector_file_still_returns_gdf(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_file

        shp = tmp_path / "rivers.shp"
        _make_lines_gdf().to_file(shp)
        cfg = HydrographySourceConfig(source="file", path=shp)
        result = load_file(cfg)
        assert isinstance(result, gpd.GeoDataFrame)

    def test_directory_prefers_raster_over_vector(self, tmp_path):
        """When a directory has both TIF and SHP, TIF wins."""
        from hydromodpy.data.variables.hydrography.custom import load_file

        _make_lines_gdf().to_file(tmp_path / "rivers.shp")
        _write_dummy_tif(tmp_path / "streams.tif")
        cfg = HydrographySourceConfig(source="file", path=tmp_path)
        result = load_file(cfg)
        assert isinstance(result, Path)

    def test_empty_dir_raises(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_file

        subdir = tmp_path / "empty"
        subdir.mkdir()
        cfg = HydrographySourceConfig(source="file", path=subdir)
        with pytest.raises(FileNotFoundError):
            load_file(cfg)

    def test_raster_extensions_constant(self):
        from hydromodpy.data.variables.hydrography.custom import _RASTER_EXTENSIONS

        assert "*.tif" in _RASTER_EXTENSIONS
        assert "*.tiff" in _RASTER_EXTENSIONS


@pytest.mark.fast
class TestVariableTifPipeline:
    """The variable should use _load_from_tif when custom returns a Path."""

    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_tif_custom_skips_vector_pipeline(self, mock_backend_factory, tmp_path):
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        # Write a TIF with data inside the watershed bbox
        tif = tmp_path / "input_streams.tif"
        _write_dummy_tif(tif, crs="EPSG:2154")

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "file", "path": str(tif)}],
            mask_path=inputs.mask_path,
        )
        mgr = HydrographyVariable(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)
        result = mgr.load()

        assert isinstance(result, LoadResult)
        assert _hydrography_vector_path(result) is None
        assert _hydrography_raster_path(result).endswith("streams.tif")
        assert isinstance(_hydrography_array(result), np.ndarray)
        # Vector rasterization backend should NOT have been called
        backend.raster.vector_lines_to_raster.assert_not_called()

    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_tif_array_negative_to_nan(self, mock_backend_factory, tmp_path):
        """Negative values in the TIF should become NaN in the field array."""
        import rasterio
        from rasterio.transform import from_bounds

        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        # Write TIF with some negative values
        tif = tmp_path / "neg_streams.tif"
        shape = (100, 100)
        transform = from_bounds(300000, 6700000, 400000, 6800000, shape[1], shape[0])
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
            transform=transform,
        ) as ds:
            ds.write(data, 1)

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "file", "path": str(tif)}],
            mask_path=inputs.mask_path,
        )
        mgr = HydrographyVariable(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)
        result = mgr.load()

        assert np.any(np.isnan(_hydrography_array(result)))


@pytest.mark.fast
class TestCacheRows:
    """Test cache hit, miss and sidecar, force_refresh, and subsumption."""

    def _make_cached_manager(self, tmp_path, *, force_refresh=False):
        from hydromodpy.data.provenance.sidecars import CacheIndex
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        data_dir = tmp_path / "cache"
        data_dir.mkdir()
        index = CacheIndex(data_dir)

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "osm", "force_refresh": force_refresh}],
            mask_path=inputs.mask_path,
        )
        mgr = HydrographyVariable(
            config=cfg,
            out_path=tmp_path,
            base_raster=inputs.base_raster,
            index=index,
            data_dir=data_dir,
        )
        return mgr, index, data_dir

    @patch("hydromodpy.data.variables.hydrography.apis.osm.fetch")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_force_refresh_bypasses_cache(self, mock_backend_factory, mock_osm_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        mgr, index, data_dir = self._make_cached_manager(tmp_path, force_refresh=True)

        lines = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(-1.5, 48.2), (-1.4, 48.3)])],
            crs="EPSG:4326",
        )
        mock_osm_fetch.return_value = lines

        tif_path = tmp_path / PREPROCESSING_DIR / "hydrography" / "streams.tif"
        tif_path.parent.mkdir(parents=True, exist_ok=True)
        _write_dummy_tif(tif_path)

        mgr.load()
        assert mock_osm_fetch.call_count == 1

        # Even with cache entry, force_refresh should re-fetch
        mgr2 = HydrographyVariable(
            config=mgr.config,
            out_path=tmp_path,
            base_raster=mgr._base_raster,
            index=index,
            data_dir=data_dir,
        )
        mgr2.load()
        assert mock_osm_fetch.call_count == 2

    def test_no_index_skips_cache(self, tmp_path):
        """Without an index, _try_load_cached returns None."""
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyVariable(
            config=cfg,
            out_path=tmp_path,
            base_raster=inputs.base_raster,
            index=None,
            data_dir=None,
        )
        result = mgr._try_load_cached("osm", (-2, 47, -1, 49))
        assert result is None

    def test_subsume_removes_smaller_bbox(self, tmp_path):
        """After registering a bigger bbox, smaller one is subsumed."""
        from hydromodpy.data.provenance.sidecars import CacheIndex

        data_dir = tmp_path / "cache"
        data_dir.mkdir()
        index = CacheIndex(data_dir)

        # Record a small bbox
        small_gpkg = data_dir / "small.gpkg"
        _make_lines_gdf().to_file(small_gpkg, driver="GPKG")
        index.record(
            small_gpkg,
            variable="hydrography",
            source="osm",
            bbox=(-2.0, 47.5, -1.5, 48.0),
            crs="EPSG:4326",
        )

        # Record a bigger bbox and subsume
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
        # Only the big row remains, and the small file left with its sidecar
        assert index.rows(variable="hydrography") == [big]
        assert not small_gpkg.exists()
        assert not (data_dir / "small.gpkg.json").exists()

    def test_a_user_file_is_never_subsumed(self, tmp_path):
        """A file of the user is no row, so a bigger box leaves it alone."""
        from hydromodpy.data.provenance.sidecars import CacheIndex

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


@pytest.mark.fast
class TestHydrographyMetadata:
    def test_vector_path_none_allowed(self):
        arr = np.zeros((10, 10))
        result = _make_hydrography_load_result(
            array=arr,
            raster_path="/tmp/s.tif",
            vector_path=None,
        )
        assert _hydrography_vector_path(result) is None
        assert _hydrography_raster_path(result) == "/tmp/s.tif"

    def test_vector_path_str(self):
        arr = np.zeros((10, 10))
        result = _make_hydrography_load_result(
            array=arr,
            raster_path="/tmp/s.tif",
            vector_path="/tmp/s.shp",
        )
        assert _hydrography_vector_path(result) == "/tmp/s.shp"


@pytest.mark.fast
class TestDataStoreHydrography:
    @patch("hydromodpy.data.variables.hydrography.variable.HydrographyVariable.load")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_load_hydrography_delegates(self, mock_backend, mock_load, tmp_path):
        from hydromodpy.data.loading.store import DataStore

        mock_load.return_value = _make_hydrography_load_result(
            raster_path="/tmp/s.tif",
            vector_path=None,
        )

        # Create minimal workspace
        (tmp_path / "data").mkdir()
        store = DataStore(workspace_root=tmp_path)

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        result = store.load_hydrography(cfg, out_path=tmp_path, base_raster=inputs.base_raster)
        assert isinstance(result, LoadResult)
        mock_load.assert_called_once()


pytestmark = pytest.mark.fast


_FETCH = "hydromodpy.data.variables.hydrography.variable.HydrographyVariable._fetch_from_source"


_BACKEND = "hydromodpy.catchment.delineation.get_whitebox_backend"


def _reaches(permanence: list[str] | None, *, x0: float = 350000.0) -> gpd.GeoDataFrame:
    """Parallel reaches inside the fake watershed, one per entry."""
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


def _manager(tmp_path: Path, sources: list[dict]):
    from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=sources, mask_path=inputs.mask_path)
    return HydrographyVariable(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)


def _permanent_path(tmp_path: Path) -> Path:
    return (
        tmp_path
        / PREPROCESSING_DIR
        / "hydrography"
        / HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_VECTOR_FILENAME
    )


def _metadata(result) -> dict:
    return result.fields[0].metadata


@patch(_FETCH)
@patch(_BACKEND)
def test_a_network_with_no_permanent_reach_writes_no_permanent_file(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["intermittent", "dry"])

    result = _manager(tmp_path, [{"source": "osm"}]).load()

    assert _metadata(result)["permanent_vector_path"] is None


def _cached_manager(tmp_path: Path, index, source: dict):
    from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=[source], mask_path=inputs.mask_path)
    return HydrographyVariable(
        config=cfg,
        out_path=tmp_path,
        base_raster=inputs.base_raster,
        index=index,
        data_dir=tmp_path / "cache",
    )


def _index(tmp_path: Path):
    from hydromodpy.data.provenance.sidecars import CacheIndex

    return CacheIndex(tmp_path / "cache")


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_the_same_box_is_served_from_disk(backend_factory, fetch, tmp_path: Path) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent"])
    index = _index(tmp_path)

    _cached_manager(tmp_path, index, {"source": "bdtopage"}).load()
    _cached_manager(tmp_path, index, {"source": "bdtopage"}).load()

    assert fetch.call_count == 1


@patch("hydromodpy.data.variables.hydrography.apis.osm.fetch")
@patch(_BACKEND)
def test_a_row_fetched_for_another_question_is_a_miss(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(None).to_crs("EPSG:4326")
    index = _index(tmp_path)

    _cached_manager(tmp_path, index, {"source": "osm", "waterway_types": ["river"]}).load()
    _cached_manager(tmp_path, index, {"source": "osm", "waterway_types": ["river"]}).load()
    assert fetch.call_count == 1
    _cached_manager(tmp_path, index, {"source": "osm", "waterway_types": ["canal"]}).load()

    assert fetch.call_count == 2, "other waterway types over the same box are not the cached ones"


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_a_row_recorded_before_the_question_was_is_still_served(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    index = _index(tmp_path)
    old = tmp_path / "cache" / "bdtopage_old.gpkg"
    old.parent.mkdir(parents=True)
    _reaches(["permanent"]).to_crs("EPSG:4326").to_file(old, driver="GPKG")
    index.record(
        old,
        variable="hydrography",
        source="bdtopage",
        bbox=(0.0, 0.0, 1e7, 1e7),
        crs="EPSG:4326",
    )

    _cached_manager(tmp_path, index, {"source": "bdtopage"}).load()

    assert fetch.call_count == 0


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_a_permanent_copy_whose_full_answer_is_gone_is_removed(
    backend_factory, fetch, tmp_path: Path
) -> None:
    """The cache unlinks a subsumed answer; its permanent copy goes with it."""
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent"])
    orphan = tmp_path / "cache" / "hydrography_bdtopage_permanent_0badf00d.gpkg"
    orphan.parent.mkdir(parents=True)
    _reaches(["permanent"]).to_file(orphan, driver="GPKG")

    _cached_manager(tmp_path, _index(tmp_path), {"source": "bdtopage"}).load()

    assert not orphan.exists()
    assert len(list((tmp_path / "cache").glob("hydrography_bdtopage_permanent_*.gpkg"))) == 1


def _watershed_wgs84(path: Path) -> Path:
    """A mask over Rennes, in degrees, written where the caller asks."""
    gpd.GeoDataFrame(
        geometry=[Polygon([(-1.8, 48.0), (-1.5, 48.0), (-1.5, 48.3), (-1.8, 48.3)])],
        crs="EPSG:4326",
    ).to_file(path)
    return path


@pytest.mark.fast
def test_the_variable_refuses_a_geographic_object():
    """The parameter is gone, not ignored."""
    with pytest.raises(TypeError, match="geographic"):
        HydrographyVariable(config=None, out_path=".", geographic=object())


def _record_the_extent(monkeypatch) -> list:
    """Intercept the port call and keep the extent the manager built."""
    seen: list = []

    def _fetch(source, extent):
        seen.append((source, extent))
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    monkeypatch.setattr(
        "hydromodpy.data.variables.hydrography.variable.fetch_network",
        _fetch,
    )
    return seen


@pytest.mark.fast
def test_a_section_without_a_mask_is_refused_by_name(tmp_path, monkeypatch):
    """No extent is a refusal that names the field, not an AttributeError."""
    _record_the_extent(monkeypatch)
    cfg = HydrographyConfig(sources=[{"source": "osm"}])
    with patch("hydromodpy.catchment.delineation.get_whitebox_backend"):
        manager = HydrographyVariable(config=cfg, out_path=tmp_path)
    with pytest.raises(ValueError, match="mask_path"):
        manager._fetch_from_source(cfg.sources[0])


@pytest.mark.fast
def test_the_request_box_leaves_in_the_crs_the_source_declares(tmp_path, monkeypatch):
    """The three hydrography sources declare degrees; the mask is in meters.

    Anti-vacuity: the Lambert-93 bounds of the fixture are around
    ``(300000, 6700000)``. Handing them over unconverted is the defect F5d-1
    removed from the raster managers, and it would fail every assertion here.
    The CRS is no longer a literal in the manager: it is read off the source,
    so a source answering in another frame is asked in that one.
    """
    seen = _record_the_extent(monkeypatch)
    inputs = _fake_inputs(tmp_path, crs="EPSG:2154")
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
    with patch("hydromodpy.catchment.delineation.get_whitebox_backend"):
        manager = HydrographyVariable(config=cfg, out_path=tmp_path)

    manager._fetch_from_source(cfg.sources[0])

    source, extent = seen[0]
    assert extent.crs == source.extent_crs == "EPSG:4326"
    lon_min, lat_min, lon_max, lat_max = extent.bbox
    assert -3.0 < lon_min < lon_max < 0.0, (lon_min, lon_max)
    assert 47.0 < lat_min < lat_max < 50.0, (lat_min, lat_max)


@pytest.mark.fast
def test_rasterising_without_a_reference_grid_is_refused_by_name(tmp_path):
    """``base_raster`` replaced ``geographic.watershed_dem``, and it is required."""
    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
    with patch("hydromodpy.catchment.delineation.get_whitebox_backend"):
        manager = HydrographyVariable(config=cfg, out_path=tmp_path)
    with pytest.raises(ValueError, match="base_raster"):
        manager._rasterize(inputs.mask_path, "FID")


@pytest.mark.fast
def test_the_loader_fills_a_mask_declared_on_the_section(tmp_path):
    """The generalization hydrography needs, and the per-source fill it kept."""
    watershed = tmp_path / "watershed.shp"
    result = SimpleNamespace(
        setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=watershed))
    )
    cfg = HydrographyConfig(sources=[{"source": "osm"}])

    DataLoader._apply_default_masks(cfg, result)

    assert cfg.mask_path == watershed


@pytest.mark.fast
def test_the_loader_leaves_an_authored_section_mask_alone(tmp_path):
    """Anti-vacuity for the fill: it is a default, not an override."""
    authored = tmp_path / "authored.gpkg"
    result = SimpleNamespace(
        setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=tmp_path / "ws.shp"))
    )
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=authored)

    DataLoader._apply_default_masks(cfg, result)

    assert cfg.mask_path == authored
