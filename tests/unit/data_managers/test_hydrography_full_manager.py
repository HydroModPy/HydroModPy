"""Manager-pipeline tests for the hydrography variable manager.

Covers the custom loader (vector + TIF), the LoadResult contract and
metadata accessors, the HydrographyManager rasterisation pipeline with the
stub Whitebox backend, the TIF fast-path, the catalog cache (hit/miss/
force_refresh/subsume), and the DataStore delegation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
)

from ._test_hydrography_full_builders import (
    WhiteboxStubBackend,
    _fake_geographic,
    _hydrography_array,
    _hydrography_raster_path,
    _hydrography_record,
    _hydrography_vector_path,
    _make_hydrography_load_result,
    _make_lines_gdf,
    _write_dummy_tif,
)

# =====================================================================
# 5. LoadResult contract
# =====================================================================


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


# =====================================================================
# 6. Custom loader
# =====================================================================


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
        from hydromodpy.data.variables.hydrography.custom import load_custom

        gpkg = tmp_path / "rivers.gpkg"
        _make_lines_gdf().to_file(gpkg, driver="GPKG")
        cfg = HydrographySourceConfig(source="custom", path=gpkg)
        gdf = load_custom(cfg)
        assert not gdf.empty

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


# =====================================================================
# 10. HydrographyManager pipeline (mocked backend)
# =====================================================================


@pytest.mark.fast
class TestHydrographyManager:
    def _make_manager(self, tmp_path, sources, crs="EPSG:2154"):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        geo = _fake_geographic(tmp_path, crs=crs)
        cfg = HydrographyConfig(sources=sources)
        return HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

    def test_data_folder_created(self, tmp_path):
        mgr = self._make_manager(tmp_path, [{"source": "osm"}])
        assert (tmp_path / ".solver_scratch/_preprocessing" / "hydrography").is_dir()

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
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

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

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
    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
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

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        result = mgr.load()
        method_names = backend.method_names()
        assert "vector_polygons_to_raster" in method_names
        assert "vector_lines_to_raster" not in method_names
        assert isinstance(result, LoadResult)

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
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

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        result = mgr.load()
        method_names = backend.method_names()
        assert "vector_points_to_raster" in method_names
        assert "vector_lines_to_raster" not in method_names
        assert isinstance(result, LoadResult)

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
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

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "bdtopage"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        mgr.load()

        # Verify the saved shapefile now has FID column
        saved_shp = tmp_path / ".solver_scratch/_preprocessing" / "hydrography" / "streams.shp"
        saved_gdf = gpd.read_file(saved_shp)
        assert "FID" in saved_gdf.columns
        assert list(saved_gdf["FID"]) == [1, 2]

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    def test_all_sources_empty_raises(self, mock_fetch, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        mock_fetch.return_value = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        with pytest.raises(ValueError, match="empty"):
            mgr.load()

    def test_get_bbox_wgs84(self, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        bbox = mgr._get_bbox_wgs84()
        assert len(bbox) == 4
        lon_min, lat_min, lon_max, lat_max = bbox
        # Roughly France area after reprojection from EPSG:2154
        assert -10 < lon_min < lon_max < 15
        assert 40 < lat_min < lat_max < 55

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
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

        geo = _fake_geographic(tmp_path, crs="EPSG:2154")
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)

        result = mgr.load()

        # The saved shapefile should be in project CRS, not WGS84
        saved_gdf = gpd.read_file(_hydrography_vector_path(result))
        assert saved_gdf.crs is not None
        assert "2154" in str(saved_gdf.crs)


# =====================================================================
# 15. Custom loader - TIF support
# =====================================================================


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


# =====================================================================
# 16. Manager - TIF pipeline
# =====================================================================


@pytest.mark.fast
class TestManagerTifPipeline:
    """Manager should use _load_from_tif when custom returns a Path."""

    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
    def test_tif_custom_skips_vector_pipeline(self, mock_backend_factory, tmp_path):
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        # Write a TIF with data inside the watershed bbox
        tif = tmp_path / "input_streams.tif"
        _write_dummy_tif(tif, crs="EPSG:2154")

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "custom", "path": str(tif)}],
        )
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)
        result = mgr.load()

        assert isinstance(result, LoadResult)
        assert _hydrography_vector_path(result) is None
        assert _hydrography_raster_path(result).endswith("streams.tif")
        assert isinstance(_hydrography_array(result), np.ndarray)
        # Vector rasterisation backend should NOT have been called
        backend.raster.vector_lines_to_raster.assert_not_called()

    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
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

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "custom", "path": str(tif)}],
        )
        mgr = HydrographyManager(config=cfg, geographic=geo, out_path=tmp_path)
        result = mgr.load()

        assert np.any(np.isnan(_hydrography_array(result)))


# =====================================================================
# 17. Catalog cache in manager
# =====================================================================


@pytest.mark.fast
class TestCatalogCacheManager:
    """Test cache hit, miss+register, force_refresh, and subsomption."""

    def _make_cached_manager(self, tmp_path, *, force_refresh=False):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        catalog = DataCatalog(db_path=None)
        data_dir = tmp_path / "cache"
        data_dir.mkdir()

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(
            sources=[{"source": "osm", "force_refresh": force_refresh}],
        )
        mgr = HydrographyManager(
            config=cfg,
            geographic=geo,
            out_path=tmp_path,
            catalog=catalog,
            data_dir=data_dir,
        )
        return mgr, catalog, data_dir

    @patch("hydromodpy.data.variables.hydrography.apis.osm.fetch")
    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
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
        tif_path = tmp_path / ".solver_scratch/_preprocessing" / "hydrography" / "streams.tif"
        tif_path.parent.mkdir(parents=True, exist_ok=True)
        _write_dummy_tif(tif_path)

        mgr.load()
        assert mock_osm_fetch.call_count == 1

        # Catalog should have an entry
        df = catalog.list_entries(variable="hydrography")
        assert len(df) == 1

        # GPKG file should exist in data_dir
        gpkg_files = list(data_dir.glob("*.gpkg"))
        assert len(gpkg_files) == 1

        # Second call - should use cache, not call API again
        mgr2 = HydrographyManager(
            config=mgr.config,
            geographic=mgr.geographic,
            out_path=tmp_path,
            catalog=catalog,
            data_dir=data_dir,
        )
        mgr2.load()
        # API was NOT called again
        assert mock_osm_fetch.call_count == 1

    @patch("hydromodpy.data.variables.hydrography.apis.osm.fetch")
    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
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

        tif_path = tmp_path / ".solver_scratch/_preprocessing" / "hydrography" / "streams.tif"
        tif_path.parent.mkdir(parents=True, exist_ok=True)
        _write_dummy_tif(tif_path)

        mgr.load()
        assert mock_osm_fetch.call_count == 1

        # Even with cache entry, force_refresh should re-fetch
        mgr2 = HydrographyManager(
            config=mgr.config,
            geographic=mgr.geographic,
            out_path=tmp_path,
            catalog=catalog,
            data_dir=data_dir,
        )
        mgr2.load()
        assert mock_osm_fetch.call_count == 2

    def test_no_catalog_skips_cache(self, tmp_path):
        """Without catalog, _try_load_cached returns None."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        mgr = HydrographyManager(
            config=cfg,
            geographic=geo,
            out_path=tmp_path,
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


# =====================================================================
# 18. LoadResult with optional vector path
# =====================================================================


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


# =====================================================================
# 20. DataStore - load_hydrography method
# =====================================================================


@pytest.mark.fast
class TestDataStoreHydrography:
    def test_load_hydrography_method_exists(self):
        from hydromodpy.data.store import DataStore

        assert hasattr(DataStore, "load_hydrography")

    @patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager.load")
    @patch("hydromodpy.spatial.delineation.get_whitebox_backend")
    def test_load_hydrography_delegates(self, mock_backend, mock_load, tmp_path):
        from hydromodpy.data.store import DataStore

        mock_load.return_value = _make_hydrography_load_result(
            raster_path="/tmp/s.tif",
            vector_path=None,
        )

        # Create minimal workspace
        (tmp_path / "data").mkdir()
        store = DataStore(workspace_root=tmp_path)

        geo = _fake_geographic(tmp_path)
        cfg = HydrographyConfig(sources=[{"source": "osm"}])
        result = store.load_hydrography(cfg, geographic=geo, out_path=tmp_path)
        assert isinstance(result, LoadResult)
        mock_load.assert_called_once()
