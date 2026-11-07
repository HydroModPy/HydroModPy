"""The hydrography manager: loading, the permanent network and the extent seam."""

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
from hydromodpy.core.state.scratch import preprocessing_dir
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import INPUT_FILES_KEY
from hydromodpy.data.loading.loader import DataManagersRuntimeLoader
from hydromodpy.data.source.permanence import PERMANENCE_COLUMN
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)
from hydromodpy.data.variables.hydrography.manager import HydrographyManager
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

    def test_load_shp_file(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        shp = self._write_shp(tmp_path / "rivers.shp")
        cfg = HydrographySourceConfig(source="custom", path=shp)
        gdf = load_custom(cfg)
        assert not gdf.empty
        assert gdf.crs is not None

    def test_load_gpkg_file(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import SOURCE_PATH_ATTR, load_custom

        gpkg = tmp_path / "rivers.gpkg"
        _make_lines_gdf().to_file(gpkg, driver="GPKG")
        cfg = HydrographySourceConfig(source="custom", path=gpkg)
        gdf = load_custom(cfg)
        assert not gdf.empty
        assert gdf.attrs[SOURCE_PATH_ATTR] == str(gpkg)

    def test_load_geojson_file(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        gj = tmp_path / "rivers.geojson"
        _make_lines_gdf().to_file(gj, driver="GeoJSON")
        cfg = HydrographySourceConfig(source="custom", path=gj)
        gdf = load_custom(cfg)
        assert not gdf.empty

    def test_directory_auto_detection(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        subdir = tmp_path / "data"
        subdir.mkdir()
        self._write_shp(subdir / "streams.shp")
        cfg = HydrographySourceConfig(source="custom", path=subdir)
        gdf = load_custom(cfg)
        assert not gdf.empty

    def test_directory_empty_raises(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        cfg = HydrographySourceConfig(source="custom", path=empty_dir)
        with pytest.raises(FileNotFoundError, match="No vector or raster file"):
            load_custom(cfg)


@pytest.mark.fast
class TestHydrographyManager:
    def _make_manager(self, tmp_path, sources, crs="EPSG:2154"):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        inputs = _fake_inputs(tmp_path, crs=crs)
        cfg = HydrographyConfig(sources=sources, mask_path=inputs.mask_path)
        return HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

    def test_data_folder_created(self, tmp_path):
        mgr = self._make_manager(tmp_path, [{"source": "osm"}])
        assert (tmp_path / PREPROCESSING_DIR / "hydrography").is_dir()

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_load_pipeline_line_geometry(self, mock_backend_factory, mock_fetch, tmp_path):
        """Full pipeline with LineString data and stub backend."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        # Prepare fetched data in project CRS
        lines_gdf = _make_lines_gdf(crs="EPSG:2154", n=3)
        # Shift coords into watershed bbox
        lines_gdf.geometry = [
            LineString([(350000 + i * 100, 6750000), (350000 + i * 100, 6751000)]) for i in range(3)
        ]
        mock_fetch.return_value = lines_gdf

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        result = mgr.load()

        assert isinstance(result, LoadResult)
        assert _hydrography_vector_path(result).endswith("streams.shp")
        assert _hydrography_raster_path(result).endswith("streams.tif")
        assert isinstance(_hydrography_array(result), np.ndarray)

        # Stub backend dispatched to the line rasteriser, not polygon/point.
        method_names = backend.method_names()
        assert "vector_lines_to_raster" in method_names
        assert "vector_polygons_to_raster" not in method_names
        assert "vector_points_to_raster" not in method_names

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_load_pipeline_polygon_geometry(self, mock_backend_factory, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

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
        mgr = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        result = mgr.load()
        method_names = backend.method_names()
        assert "vector_polygons_to_raster" in method_names
        assert "vector_lines_to_raster" not in method_names
        assert isinstance(result, LoadResult)

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_load_pipeline_point_geometry(self, mock_backend_factory, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

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
        mgr = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        result = mgr.load()
        method_names = backend.method_names()
        assert "vector_points_to_raster" in method_names
        assert "vector_lines_to_raster" not in method_names
        assert isinstance(result, LoadResult)

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_synthetic_fid_field(self, mock_backend_factory, mock_fetch, tmp_path):
        """When rasterize_field doesn't exist in data, manager creates sequential FID."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        gdf = gpd.GeoDataFrame(
            {"name": ["Aven", "Odet"]},  # No "FID" column
            geometry=[
                LineString([(350000, 6750000), (350500, 6750500)]),
                LineString([(351000, 6751000), (351500, 6751500)]),
            ],
            crs="EPSG:2154",
        )
        mock_fetch.return_value = gdf

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "bdtopage"}], mask_path=inputs.mask_path)
        mgr = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        mgr.load()

        # Verify the saved shapefile now has FID column
        saved_shp = tmp_path / PREPROCESSING_DIR / "hydrography" / "streams.shp"
        saved_gdf = gpd.read_file(saved_shp)
        assert "FID" in saved_gdf.columns
        assert list(saved_gdf["FID"]) == [1, 2]

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    def test_all_sources_empty_raises(self, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        mock_fetch.return_value = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        with pytest.raises(ValueError, match="empty"):
            mgr.load()

    def test_the_request_extent_is_reprojected_for_the_source(self, tmp_path, monkeypatch):
        import geopandas as gpd

        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        seen = []

        def _fetch(source, extent):
            seen.append(extent)
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

        monkeypatch.setattr(
            "hydromodpy.data.variables.hydrography.manager.fetch_network",
            _fetch,
        )
        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        mgr._fetch_from_source(cfg.sources[0])

        lon_min, lat_min, lon_max, lat_max = seen[0].bbox
        # Roughly France area after reprojection from EPSG:2154
        assert -10 < lon_min < lon_max < 15
        assert 40 < lat_min < lat_max < 55

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_crs_reprojection(self, mock_backend_factory, mock_fetch, tmp_path):
        """Data in EPSG:4326 gets reprojected to project CRS before clip."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        # Data in WGS84 - inside the watershed after reprojection
        gdf_4326 = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(-1.5, 48.2), (-1.4, 48.3)])],
            crs="EPSG:4326",
        )
        mock_fetch.return_value = gdf_4326

        backend = WhiteboxStubBackend()
        mock_backend_factory.return_value = backend

        inputs = _fake_inputs(tmp_path, crs="EPSG:2154")
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

        result = mgr.load()

        # The saved shapefile should be in project CRS, not WGS84
        saved_gdf = gpd.read_file(_hydrography_vector_path(result))
        assert saved_gdf.crs is not None
        assert "2154" in str(saved_gdf.crs)


@pytest.mark.fast
class TestCustomLoaderTif:
    """TIF files should be returned as Path, not GeoDataFrame."""

    def test_tif_file_returns_path(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        tif = tmp_path / "hydro.tif"
        _write_dummy_tif(tif)
        cfg = HydrographySourceConfig(source="custom", path=tif)
        result = load_custom(cfg)
        assert isinstance(result, Path)
        assert result == tif

    def test_tiff_file_returns_path(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        tif = tmp_path / "hydro.tiff"
        _write_dummy_tif(tif)
        cfg = HydrographySourceConfig(source="custom", path=tif)
        result = load_custom(cfg)
        assert isinstance(result, Path)

    def test_tif_in_directory(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        subdir = tmp_path / "data"
        subdir.mkdir()
        tif = subdir / "streams.tif"
        _write_dummy_tif(tif)
        cfg = HydrographySourceConfig(source="custom", path=subdir)
        result = load_custom(cfg)
        assert isinstance(result, Path)
        assert result.suffix == ".tif"

    def test_vector_file_still_returns_gdf(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        shp = tmp_path / "rivers.shp"
        _make_lines_gdf().to_file(shp)
        cfg = HydrographySourceConfig(source="custom", path=shp)
        result = load_custom(cfg)
        assert isinstance(result, gpd.GeoDataFrame)

    def test_directory_prefers_raster_over_vector(self, tmp_path):
        """When a directory has both TIF and SHP, TIF wins."""
        from hydromodpy.data.variables.hydrography.custom import load_custom

        _make_lines_gdf().to_file(tmp_path / "rivers.shp")
        _write_dummy_tif(tmp_path / "streams.tif")
        cfg = HydrographySourceConfig(source="custom", path=tmp_path)
        result = load_custom(cfg)
        assert isinstance(result, Path)

    def test_empty_dir_raises(self, tmp_path):
        from hydromodpy.data.variables.hydrography.custom import load_custom

        subdir = tmp_path / "empty"
        subdir.mkdir()
        cfg = HydrographySourceConfig(source="custom", path=subdir)
        with pytest.raises(FileNotFoundError):
            load_custom(cfg)

    def test_raster_extensions_constant(self):
        from hydromodpy.data.variables.hydrography.custom import _RASTER_EXTENSIONS

        assert "*.tif" in _RASTER_EXTENSIONS
        assert "*.tiff" in _RASTER_EXTENSIONS


@pytest.mark.fast
class TestManagerTifPipeline:
    """Manager should use _load_from_tif when custom returns a Path."""

    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_tif_custom_skips_vector_pipeline(self, mock_backend_factory, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        # Write a TIF with data inside the watershed bbox
        tif = tmp_path / "input_streams.tif"
        _write_dummy_tif(tif, crs="EPSG:2154")

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "custom", "path": str(tif)}],
            mask_path=inputs.mask_path,
        )
        mgr = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)
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

        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

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
            sources=[{"source": "custom", "path": str(tif)}],
            mask_path=inputs.mask_path,
        )
        mgr = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)
        result = mgr.load()

        assert np.any(np.isnan(_hydrography_array(result)))


@pytest.mark.fast
class TestCatalogCacheManager:
    """Test cache hit, miss+register, force_refresh, and subsomption."""

    def _make_cached_manager(self, tmp_path, *, force_refresh=False):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        catalog = DataCatalog(db_path=None)
        data_dir = tmp_path / "cache"
        data_dir.mkdir()

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "osm", "force_refresh": force_refresh}],
            mask_path=inputs.mask_path,
        )
        mgr = HydrographyManager(
            config=cfg,
            out_path=tmp_path,
            base_raster=inputs.base_raster,
            catalog=catalog,
            data_dir=data_dir,
        )
        return mgr, catalog, data_dir

    @patch("hydromodpy.data.variables.hydrography.apis.osm.fetch")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_cache_miss_then_hit(self, mock_backend_factory, mock_osm_fetch, tmp_path):
        """First call fetches API + registers; second call hits cache."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        mgr, catalog, data_dir = self._make_cached_manager(tmp_path)

        # Prepare lines inside watershed
        lines = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(-1.5, 48.2), (-1.4, 48.3)])],
            crs="EPSG:4326",
        )
        mock_osm_fetch.return_value = lines

        # Write fake TIF for read_tif_array
        tif_path = tmp_path / PREPROCESSING_DIR / "hydrography" / "streams.tif"
        tif_path.parent.mkdir(parents=True, exist_ok=True)
        _write_dummy_tif(tif_path)

        fetched = mgr.load()
        assert mock_osm_fetch.call_count == 1

        # Catalog should have an entry
        df = catalog.list_entries(variable="hydrography")
        assert len(df) == 1

        # GPKG file should exist in data_dir
        gpkg_files = [path for path in data_dir.glob("*.gpkg") if "_permanent_" not in path.name]
        assert len(gpkg_files) == 1
        # The record names the cached answer and its provider, not the raster of the run.
        assert _hydrography_record(fetched).metadata[INPUT_FILES_KEY] == [
            {"provider": "osm", "path": str(gpkg_files[0])}
        ]

        # Second call - should use cache, not call API again
        mgr2 = HydrographyManager(
            config=mgr.config,
            out_path=tmp_path,
            base_raster=mgr._base_raster,
            catalog=catalog,
            data_dir=data_dir,
        )
        cached = mgr2.load()
        # API was NOT called again
        assert mock_osm_fetch.call_count == 1
        assert _hydrography_record(cached).metadata[INPUT_FILES_KEY] == [
            {"provider": "osm", "path": str(gpkg_files[0])}
        ]

    @patch("hydromodpy.data.variables.hydrography.apis.osm.fetch")
    @patch("hydromodpy.catchment.delineation.get_whitebox_backend")
    def test_force_refresh_bypasses_cache(self, mock_backend_factory, mock_osm_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        mgr, catalog, data_dir = self._make_cached_manager(tmp_path, force_refresh=True)

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
        mgr2 = HydrographyManager(
            config=mgr.config,
            out_path=tmp_path,
            base_raster=mgr._base_raster,
            catalog=catalog,
            data_dir=data_dir,
        )
        mgr2.load()
        assert mock_osm_fetch.call_count == 2

    def test_no_catalog_skips_cache(self, tmp_path):
        """Without catalog, _try_load_cached returns None."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        inputs = _fake_inputs(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
        mgr = HydrographyManager(
            config=cfg,
            out_path=tmp_path,
            base_raster=inputs.base_raster,
            catalog=None,
            data_dir=None,
        )
        result = mgr._try_load_cached("osm", (-2, 47, -1, 49))
        assert result is None

    def test_subsume_removes_smaller_bbox(self, tmp_path):
        """After registering a bigger bbox, smaller one is subsumed."""
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        catalog = DataCatalog(db_path=None)
        data_dir = tmp_path / "cache"
        data_dir.mkdir()

        # Register a small bbox
        small_gpkg = data_dir / "small.gpkg"
        _make_lines_gdf().to_file(small_gpkg, driver="GPKG")
        small_id = catalog.register(
            variable="hydrography",
            source="osm",
            file_path=str(small_gpkg),
            bbox=(-2.0, 47.5, -1.5, 48.0),
            crs="EPSG:4326",
            is_custom=False,
            file_mtime=0.0,
        )

        # Register a bigger bbox and subsume
        big_gpkg = data_dir / "big.gpkg"
        _make_lines_gdf().to_file(big_gpkg, driver="GPKG")
        big_id = catalog.register(
            variable="hydrography",
            source="osm",
            file_path=str(big_gpkg),
            bbox=(-3.0, 47.0, -1.0, 49.0),
            crs="EPSG:4326",
            is_custom=False,
            file_mtime=0.0,
        )
        removed = catalog.subsume_entries(
            variable="hydrography",
            source="osm",
            bbox=(-3.0, 47.0, -1.0, 49.0),
            date_start=None,
            date_end=None,
            exclude_id=big_id,
        )
        assert removed == 1
        # Only the big entry remains
        df = catalog.list_entries(variable="hydrography")
        assert len(df) == 1
        assert df.iloc[0]["id"] == big_id

    def test_custom_never_subsumed(self, tmp_path):
        """Custom entries (is_custom=True) are never subsumed."""
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        catalog = DataCatalog(db_path=None)
        catalog.register(
            variable="hydrography",
            source="osm",
            file_path="/tmp/custom.gpkg",
            bbox=(-2.0, 47.5, -1.5, 48.0),
            crs="EPSG:4326",
            is_custom=True,
            file_mtime=0.0,
        )
        removed = catalog.subsume_entries(
            variable="hydrography",
            source="osm",
            bbox=(-3.0, 47.0, -1.0, 49.0),
            date_start=None,
            date_end=None,
        )
        assert removed == 0


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
    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager.load")
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


_FETCH = "hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source"


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
    from hydromodpy.data.variables.hydrography.manager import HydrographyManager

    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=sources, mask_path=inputs.mask_path)
    return HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)


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
def test_the_permanent_reaches_are_written_beside_the_full_network(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent", "intermittent", "permanent"])

    result = _manager(tmp_path, [{"source": "osm"}]).load()

    full = gpd.read_file(_metadata(result)["vector_path"])
    permanent = gpd.read_file(_metadata(result)["permanent_vector_path"])
    assert len(full) == 3, "the reference network keeps every reach"
    assert sorted(full[PERMANENCE_COLUMN]) == ["intermittent", "permanent", "permanent"]
    assert sorted(permanent["gid"]) == [0, 2]
    assert set(permanent[PERMANENCE_COLUMN]) == {"permanent"}
    assert Path(_metadata(result)["permanent_vector_path"]) == _permanent_path(tmp_path)


@patch(_FETCH)
@patch(_BACKEND)
def test_a_network_that_says_nothing_has_no_permanent_part(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(None)

    result = _manager(tmp_path, [{"source": "osm"}]).load()

    assert _metadata(result)["permanent_vector_path"] is None
    assert not _permanent_path(tmp_path).exists()


@patch(_FETCH)
@patch(_BACKEND)
def test_a_permanent_network_left_by_an_earlier_run_is_removed(
    backend_factory, fetch, tmp_path: Path
) -> None:
    """Switching to a source that does not say must not leave the old file to be read."""
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent", "permanent"])
    _manager(tmp_path, [{"source": "osm"}]).load()
    assert _permanent_path(tmp_path).exists()

    fetch.return_value = _reaches(None)
    result = _manager(tmp_path, [{"source": "osm"}]).load()

    assert _metadata(result)["permanent_vector_path"] is None
    assert list(_permanent_path(tmp_path).parent.glob("streams_permanent.*")) == []


@patch(_FETCH)
@patch(_BACKEND)
def test_a_network_with_no_permanent_reach_writes_no_permanent_file(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["intermittent", "dry"])

    result = _manager(tmp_path, [{"source": "osm"}]).load()

    assert _metadata(result)["permanent_vector_path"] is None


@patch(_FETCH)
@patch(_BACKEND)
def test_reaches_from_a_source_that_does_not_say_are_unknown_not_permanent(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.side_effect = [_reaches(["permanent"]), _reaches(None, x0=351000.0)]

    result = _manager(tmp_path, [{"source": "bdtopage"}, {"source": "osm"}]).load()

    full = gpd.read_file(_metadata(result)["vector_path"])
    permanent = gpd.read_file(_metadata(result)["permanent_vector_path"])
    assert sorted(full[PERMANENCE_COLUMN]) == ["permanent", "unknown", "unknown", "unknown"]
    assert len(permanent) == 1


@patch(_FETCH)
@patch(_BACKEND)
def test_sources_answering_in_two_crs_are_concatenated(
    backend_factory, fetch, tmp_path: Path
) -> None:
    """BD Topage answers in Lambert-93 and OSM in WGS84; one section may name both."""
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.side_effect = [
        _reaches(["permanent"]),
        _reaches(None, x0=351000.0).to_crs("EPSG:4326"),
    ]

    result = _manager(tmp_path, [{"source": "bdtopage"}, {"source": "osm"}]).load()

    full = gpd.read_file(_metadata(result)["vector_path"])
    assert len(full) == 4
    assert full.crs.to_epsg() == 2154


def _cached_manager(tmp_path: Path, catalog, source: dict):
    from hydromodpy.data.variables.hydrography.manager import HydrographyManager

    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=[source], mask_path=inputs.mask_path)
    return HydrographyManager(
        config=cfg,
        out_path=tmp_path,
        base_raster=inputs.base_raster,
        catalog=catalog,
        data_dir=tmp_path / "cache",
    )


def _catalog():
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    return DataCatalogDuckDB(db_path=None)


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_a_fetch_is_named_as_every_variable_names_what_it_fetched(
    backend_factory, fetch, tmp_path: Path
) -> None:
    """``hydrography_bdtopage_<hash>``, as ``geology_brgm_1m_<hash>``, and its permanent copy."""
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent", "intermittent", "permanent"])
    catalog = _catalog()

    _cached_manager(tmp_path, catalog, {"source": "bdtopage"}).load()

    names = sorted(path.name for path in (tmp_path / "cache").glob("*.gpkg"))
    assert len(names) == 2
    full_name, permanent_name = names
    token = full_name.removeprefix("hydrography_bdtopage_").removesuffix(".gpkg")
    assert len(token) == 8 and all(c in "0123456789abcdef" for c in token)
    assert permanent_name == f"hydrography_bdtopage_permanent_{token}.gpkg"
    full = gpd.read_file(tmp_path / "cache" / full_name)
    permanent = gpd.read_file(tmp_path / "cache" / permanent_name)
    assert len(full) == 3 and full.crs.to_epsg() == 2154, "kept in the CRS it came in"
    assert sorted(permanent["gid"]) == [0, 2]
    entry = catalog.find_cached(variable="hydrography", source="bdtopage")
    assert entry is not None and entry.crs == "EPSG:2154"


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_the_same_box_is_served_from_disk(backend_factory, fetch, tmp_path: Path) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent"])
    catalog = _catalog()

    _cached_manager(tmp_path, catalog, {"source": "bdtopage"}).load()
    _cached_manager(tmp_path, catalog, {"source": "bdtopage"}).load()

    assert fetch.call_count == 1


@patch("hydromodpy.data.variables.hydrography.apis.osm.fetch")
@patch(_BACKEND)
def test_an_entry_fetched_for_another_question_is_a_miss(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(None).to_crs("EPSG:4326")
    catalog = _catalog()

    _cached_manager(tmp_path, catalog, {"source": "osm", "waterway_types": ["river"]}).load()
    _cached_manager(tmp_path, catalog, {"source": "osm", "waterway_types": ["river"]}).load()
    assert fetch.call_count == 1
    _cached_manager(tmp_path, catalog, {"source": "osm", "waterway_types": ["canal"]}).load()

    assert fetch.call_count == 2, "other waterway types over the same box are not the cached ones"


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_an_entry_recorded_before_the_question_was_is_still_served(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    catalog = _catalog()
    old = tmp_path / "cache" / "bdtopage_old.gpkg"
    old.parent.mkdir(parents=True)
    _reaches(["permanent"]).to_crs("EPSG:4326").to_file(old, driver="GPKG")
    catalog.register(
        variable="hydrography",
        source="bdtopage",
        file_path=str(old),
        bbox=(0.0, 0.0, 1e7, 1e7),
        crs="EPSG:4326",
        is_custom=False,
    )

    _cached_manager(tmp_path, catalog, {"source": "bdtopage"}).load()

    assert fetch.call_count == 0


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_a_cached_answer_without_its_permanent_copy_gets_one(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent", "intermittent"])
    catalog = _catalog()
    _cached_manager(tmp_path, catalog, {"source": "bdtopage"}).load()
    (permanent,) = (tmp_path / "cache").glob("hydrography_bdtopage_permanent_*.gpkg")
    permanent.unlink()

    _cached_manager(tmp_path, catalog, {"source": "bdtopage"}).load()

    assert fetch.call_count == 1
    assert permanent.exists()


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_a_permanent_copy_whose_full_answer_is_gone_is_removed(
    backend_factory, fetch, tmp_path: Path
) -> None:
    """The catalog unlinks a subsumed answer; its permanent copy goes with it."""
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent"])
    orphan = tmp_path / "cache" / "hydrography_bdtopage_permanent_0badf00d.gpkg"
    orphan.parent.mkdir(parents=True)
    _reaches(["permanent"]).to_file(orphan, driver="GPKG")

    _cached_manager(tmp_path, _catalog(), {"source": "bdtopage"}).load()

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
def test_the_manager_refuses_a_geographic_object():
    """The parameter is gone, not ignored."""
    with pytest.raises(TypeError, match="geographic"):
        HydrographyManager(config=None, out_path=".", geographic=object())


def _record_the_extent(monkeypatch) -> list:
    """Intercept the port call and keep the extent the manager built."""
    seen: list = []

    def _fetch(source, extent):
        seen.append((source, extent))
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    monkeypatch.setattr(
        "hydromodpy.data.variables.hydrography.manager.fetch_network",
        _fetch,
    )
    return seen


@pytest.mark.fast
def test_a_section_without_a_mask_is_refused_by_name(tmp_path, monkeypatch):
    """No extent is a refusal that names the field, not an AttributeError."""
    _record_the_extent(monkeypatch)
    cfg = HydrographyConfig(sources=[{"source": "osm"}])
    with patch("hydromodpy.catchment.delineation.get_whitebox_backend"):
        manager = HydrographyManager(config=cfg, out_path=tmp_path)
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
        manager = HydrographyManager(config=cfg, out_path=tmp_path)

    manager._fetch_from_source(cfg.sources[0])

    source, extent = seen[0]
    assert extent.crs == source.extent_crs == "EPSG:4326"
    lon_min, lat_min, lon_max, lat_max = extent.bbox
    assert -3.0 < lon_min < lon_max < 0.0, (lon_min, lon_max)
    assert 47.0 < lat_min < lat_max < 50.0, (lat_min, lat_max)


@pytest.mark.fast
@patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
@patch("hydromodpy.catchment.delineation.get_whitebox_backend")
def test_the_clip_happens_in_the_frame_the_mask_declares(
    mock_backend_factory, mock_fetch, tmp_path
):
    """A degrees mask and a meters network still meet, and the output is in degrees.

    This is the read that replaced ``geographic.crs_proj``. The old code
    reprojected the network into a CRS read off the object and clipped against
    a file that was assumed to be in the same one; here the file is the only
    thing that says where anything is, so a mismatch cannot happen.
    """
    mock_backend_factory.return_value = WhiteboxStubBackend()
    mock_fetch.return_value = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(350000.0, 6780000.0), (355000.0, 6785000.0)])],
        crs="EPSG:2154",
    )

    mask_path = _watershed_wgs84(tmp_path / "mask_wgs84.shp")
    inputs = _fake_inputs(tmp_path, crs="EPSG:2154")
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=mask_path)
    manager = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

    manager.load()

    clipped = gpd.read_file(manager._data_folder / "streams.shp")
    assert not clipped.empty, "the network was dropped, so the two frames never met"
    assert "4326" in str(clipped.crs)


@pytest.mark.fast
def test_rasterising_without_a_reference_grid_is_refused_by_name(tmp_path):
    """``base_raster`` replaced ``geographic.watershed_dem``, and it is required."""
    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
    with patch("hydromodpy.catchment.delineation.get_whitebox_backend"):
        manager = HydrographyManager(config=cfg, out_path=tmp_path)
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

    DataManagersRuntimeLoader._apply_default_masks(cfg, result)

    assert cfg.mask_path == watershed


@pytest.mark.fast
def test_the_loader_leaves_an_authored_section_mask_alone(tmp_path):
    """Anti-vacuity for the fill: it is a default, not an override."""
    authored = tmp_path / "authored.gpkg"
    result = SimpleNamespace(
        setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=tmp_path / "ws.shp"))
    )
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=authored)

    DataManagersRuntimeLoader._apply_default_masks(cfg, result)

    assert cfg.mask_path == authored
