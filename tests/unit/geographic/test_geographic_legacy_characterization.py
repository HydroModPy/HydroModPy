"""Characterization tests for legacy ``hydromodpy.spatial.geographic.Geographic``.

Goal:
- lock the current public contract of the legacy class before migration,
- avoid runtime dependency on the concrete Whitebox backend by mocking it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from geopy.exc import GeocoderUnavailable
from rasterio.errors import RasterioIOError
from rasterio.features import geometry_mask, rasterize, shapes
from rasterio.transform import from_origin
from shapely.geometry import box, shape as shapely_shape

from hydromodpy.spatial.geographic.geographic import Geographic
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.dem_metadata import _resolve_dep_code


GOLDEN_FILE = (
    Path(__file__).resolve().parent / "golden" / "geographic_legacy_characterization_golden.json"
)
GOLDEN_FILE_OUTLET = (
    Path(__file__).resolve().parent
    / "golden"
    / "geographic_legacy_characterization_outlet_golden.json"
)


class _FakeLocation:
    address = "Rennes, 35000, France"


class _FakeNominatim:
    def __init__(self, *args, **kwargs):
        pass

    def reverse(self, *_args, **_kwargs):
        return _FakeLocation()


class _UnavailableNominatim:
    def __init__(self, *args, **kwargs):
        pass

    def reverse(self, *_args, **_kwargs):
        raise GeocoderUnavailable("offline")


class _FakeWhiteboxBackend:
    """Deterministic in-test substitute for the Whitebox backend file API."""

    verbose = False

    @staticmethod
    def _copy_raster(src_path: str | Path, dst_path: str | Path) -> None:
        src = Path(src_path)
        dst = Path(dst_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(str(src)) as src_ds:
            data = src_ds.read(1)
            profile = src_ds.profile.copy()
        with rasterio.open(str(dst), "w", **profile) as dst_ds:
            dst_ds.write(data, 1)

    def fill_depressions(self, dem_in: str, dem_out: str) -> None:
        self._copy_raster(dem_in, dem_out)

    def breach_depressions(self, dem_in: str, dem_out: str) -> None:
        self._copy_raster(dem_in, dem_out)

    def d8_pointer(self, dem_in: str, out_path: str, esri_pntr: bool = False) -> None:
        _ = esri_pntr
        with rasterio.open(dem_in) as src_ds:
            profile = src_ds.profile.copy()
            shape = (src_ds.height, src_ds.width)
        profile.update(dtype=np.int16, nodata=-32768, count=1)
        data = np.ones(shape, dtype=np.int16)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst_ds:
            dst_ds.write(data, 1)

    def d8_flow_accumulation(self, dem_in: str, out_path: str, log: bool = True) -> None:
        _ = log
        with rasterio.open(dem_in) as src_ds:
            profile = src_ds.profile.copy()
            shape = (src_ds.height, src_ds.width)
        profile.update(dtype=np.float32, nodata=-9999.0, count=1)
        data = np.arange(1, shape[0] * shape[1] + 1, dtype=np.float32).reshape(shape)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst_ds:
            dst_ds.write(data, 1)

    def snap_pour_points(
        self,
        pour_points: str,
        flow_accumulation: str,
        output: str,
        snap_dist: int,
    ) -> None:
        _ = flow_accumulation, snap_dist
        gdf = gpd.read_file(pour_points)
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(output)

    def watershed(
        self,
        d8_pntr: str,
        pour_pts: str,
        output: str,
        esri_pntr: bool = False,
    ) -> None:
        _ = esri_pntr
        outlet = gpd.read_file(pour_pts).geometry.iloc[0]
        with rasterio.open(d8_pntr) as src_ds:
            profile = src_ds.profile.copy()
            shape = (src_ds.height, src_ds.width)
            transform = src_ds.transform
            cols = np.arange(src_ds.width, dtype=float)
            rows = np.arange(src_ds.height, dtype=float)
            xx = transform.c + (cols + 0.5) * transform.a
            yy = transform.f + (rows + 0.5) * transform.e
            xg, yg = np.meshgrid(xx, yy)

        # Deterministic synthetic watershed: cells "upstream" of outlet in XY space.
        mask = (xg <= float(outlet.x)) & (yg <= float(outlet.y))
        if not np.any(mask):
            # Ensure at least one cell belongs to watershed if outlet is near edge.
            ci = int(np.clip(round((float(outlet.x) - transform.c) / transform.a - 0.5), 0, shape[1] - 1))
            ri = int(np.clip(round((float(outlet.y) - transform.f) / transform.e - 0.5), 0, shape[0] - 1))
            mask[ri, ci] = True

        profile.update(dtype=np.uint8, nodata=0, count=1)
        data = np.where(mask, 1, 0).astype(np.uint8)
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output, "w", **profile) as dst_ds:
            dst_ds.write(data, 1)

    def raster_to_vector_polygons(self, input_raster: str, output_shp: str) -> None:
        with rasterio.open(input_raster) as src_ds:
            arr = src_ds.read(1)
            geoms = [
                shapely_shape(geom)
                for geom, value in shapes(arr, transform=src_ds.transform)
                if int(value) == 1
            ]
            out = gpd.GeoDataFrame(
                data={"id": list(range(1, len(geoms) + 1))},
                geometry=geoms,
                crs=src_ds.crs,
            )
        Path(output_shp).parent.mkdir(parents=True, exist_ok=True)
        out.to_file(output_shp)

    def polygons_to_lines(self, in_shp: str, out_shp: str) -> None:
        gdf = gpd.read_file(in_shp)
        union_geom = gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.unary_union
        out = gpd.GeoDataFrame({"id": [1]}, geometry=[union_geom.boundary], crs=gdf.crs)
        Path(out_shp).parent.mkdir(parents=True, exist_ok=True)
        out.to_file(out_shp)

    def minimum_bounding_envelope(self, in_shp: str, out_shp: str, features: bool = False) -> None:
        _ = features
        gdf = gpd.read_file(in_shp)
        xmin, ymin, xmax, ymax = gdf.total_bounds
        out = gpd.GeoDataFrame({"id": [1]}, geometry=[box(xmin, ymin, xmax, ymax)], crs=gdf.crs)
        Path(out_shp).parent.mkdir(parents=True, exist_ok=True)
        out.to_file(out_shp)

    def clip_raster_to_polygon(
        self,
        in_raster: str,
        in_polygon: str,
        out_raster: str,
        maintain_dimensions: bool = False,
    ) -> None:
        _ = maintain_dimensions
        polygons = gpd.read_file(in_polygon)
        with rasterio.open(in_raster) as src_ds:
            data = src_ds.read(1)
            profile = src_ds.profile.copy()
            nodata = src_ds.nodata if src_ds.nodata is not None else -9999.0
            keep_mask = geometry_mask(
                [geom for geom in polygons.geometry],
                out_shape=data.shape,
                transform=src_ds.transform,
                invert=True,
            )
            clipped = np.where(keep_mask, data, nodata)
            profile.update(count=1, nodata=nodata)
        Path(out_raster).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_raster, "w", **profile) as dst_ds:
            dst_ds.write(clipped.astype(profile["dtype"]), 1)

    def modify_no_data_value(self, raster_path: str, new_value: float) -> None:
        with rasterio.open(raster_path, "r+") as dst_ds:
            dst_ds.nodata = float(new_value)

    def vector_lines_to_raster(self, in_shp: str, out_raster: str, base: str) -> None:
        lines = gpd.read_file(in_shp)
        with rasterio.open(base) as base_ds:
            profile = base_ds.profile.copy()
            transform = base_ds.transform
            shape = (base_ds.height, base_ds.width)
        profile.update(dtype=np.uint8, nodata=0, count=1)
        data = rasterize(
            [(geom, 1) for geom in lines.geometry],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )
        Path(out_raster).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_raster, "w", **profile) as dst_ds:
            dst_ds.write(data, 1)


def _write_synthetic_dem(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_origin(0.0, 1000.0, 100.0, 100.0)
    data = np.arange(100, dtype=np.float32).reshape(10, 10)
    profile = {
        "driver": "GTiff",
        "height": 10,
        "width": 10,
        "count": 1,
        "dtype": np.float32,
        "crs": "EPSG:2154",
        "transform": transform,
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst_ds:
        dst_ds.write(data, 1)


def _write_synthetic_catchment(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[box(100.0, 100.0, 700.0, 700.0)],
        crs="EPSG:2154",
    )
    gdf.to_file(path)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _build_geographic_legacy_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Geographic:
    import hydromodpy.spatial.geographic.geographic as geo_mod

    fake_wbt = _FakeWhiteboxBackend()
    monkeypatch.setattr(geo_mod, "get_whitebox_backend", lambda: fake_wbt)
    monkeypatch.setattr(geo_mod, "Nominatim", _FakeNominatim)

    dem_path = tmp_path / "inputs" / "dem.tif"
    catchment_path = tmp_path / "inputs" / "catchment.shp"
    _write_synthetic_dem(dem_path)
    _write_synthetic_catchment(catchment_path)

    cfg = GeographicConfig(
        catch_def="from_polyg_shp",
        dem_init_path=dem_path,
        polyg_shp_path=catchment_path,
        buff_area=20.0,
        crs_project="EPSG:2154",
        dem_correc_type="breach",
    )
    initializing = SimpleNamespace(catch_folder=str(tmp_path / "case_run"))
    return Geographic(config=cfg, initializing=initializing)


def _build_geographic_legacy_outlet_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Geographic:
    import hydromodpy.spatial.geographic.geographic as geo_mod

    fake_wbt = _FakeWhiteboxBackend()
    monkeypatch.setattr(geo_mod, "get_whitebox_backend", lambda: fake_wbt)
    monkeypatch.setattr(geo_mod, "Nominatim", _FakeNominatim)

    dem_path = tmp_path / "inputs" / "dem.tif"
    _write_synthetic_dem(dem_path)

    cfg = GeographicConfig(
        catch_def="from_outlet_coord",
        dem_init_path=dem_path,
        x_outlet=450.0,
        y_outlet=450.0,
        snap_dist=100,
        buff_area=20.0,
        crs_project="EPSG:2154",
        dem_correc_type="breach",
    )
    initializing = SimpleNamespace(catch_folder=str(tmp_path / "case_run_outlet"))
    return Geographic(config=cfg, initializing=initializing)


def _legacy_signature(geo: Geographic) -> dict:
    finite_box = np.isfinite(geo.dem_box_buff_data) & (geo.dem_box_buff_data != geo.nodata)
    finite_core = np.isfinite(geo.dem_data) & (geo.dem_data != geo.nodata)

    return {
        "catch_area_km2": float(geo.catch_area),
        "crs_proj": str(geo.crs_proj),
        "dep_code": int(getattr(geo, "dep_code", -1)),
        "shape_box_buff": [int(v) for v in geo.dem_box_buff_data.shape],
        "shape_buff": [int(v) for v in geo.dem_buff_data.shape],
        "shape_core": [int(v) for v in geo.dem_data.shape],
        "dx": float(geo.dx),
        "dy": float(geo.dy),
        "xmin": float(geo.xmin),
        "xmax": float(geo.xmax),
        "ymin": float(geo.ymin),
        "ymax": float(geo.ymax),
        "mean_box_buff": float(np.nanmean(np.where(finite_box, geo.dem_box_buff_data, np.nan))),
        "mean_core": float(np.nanmean(np.where(finite_core, geo.dem_data, np.nan))),
        "top_left_box_buff": float(geo.dem_box_buff_data[0, 0]),
        "center_core": float(geo.dem_data[5, 5]),
    }


def test_geographic_legacy_from_polygon_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Check legacy public artifacts and georeferencing contract on synthetic inputs."""
    geo = _build_geographic_legacy_case(tmp_path, monkeypatch)

    assert Path(geo.watershed_shp).exists()
    assert Path(geo.watershed_box_shp).exists()
    assert Path(geo.box_buff).exists()
    assert Path(geo.watershed_box_buff_dem).exists()
    assert Path(geo.watershed_dem).exists()
    assert Path(geo.watershed_contour_tif).exists()

    georef = geo.build_georeferencing()
    assert set(georef.keys()) == {"crs", "dx", "dy", "xmin", "xmax", "ymin", "ymax"}
    assert georef["crs"] == "EPSG:2154"
    assert float(georef["dx"]) == pytest.approx(100.0, abs=1e-9)
    assert float(georef["dy"]) == pytest.approx(100.0, abs=1e-9)

    domain_geographic = geo.get_domain_geographic_context()
    assert domain_geographic.catch_def == "from_polyg_shp"
    assert domain_geographic.zone_kind == "catchment"
    assert domain_geographic.watershed_shp == geo.watershed_shp
    assert domain_geographic.watershed_box_buff_dem == geo.watershed_box_buff_dem
    assert domain_geographic.box_buff_shp == geo.box_buff
    assert float(domain_geographic.catchment_area_km2) == pytest.approx(
        float(geo.catch_area),
        abs=1e-9,
    )
    assert domain_geographic.surface_topo.support is not None


def test_geographic_legacy_from_polygon_golden(
    update_goldens: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Freeze one deterministic legacy signature as non-regression baseline."""
    geo = _build_geographic_legacy_case(tmp_path, monkeypatch)
    actual = _legacy_signature(geo)

    if update_goldens:
        _write_json(GOLDEN_FILE, actual)
        return

    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_FILE)
    assert actual["shape_box_buff"] == expected["shape_box_buff"]
    assert actual["shape_buff"] == expected["shape_buff"]
    assert actual["shape_core"] == expected["shape_core"]
    assert actual["crs_proj"] == expected["crs_proj"]
    assert actual["dep_code"] == expected["dep_code"]

    for key in (
        "catch_area_km2",
        "dx",
        "dy",
        "xmin",
        "xmax",
        "ymin",
        "ymax",
        "mean_box_buff",
        "mean_core",
        "top_left_box_buff",
        "center_core",
    ):
        assert actual[key] == pytest.approx(expected[key], rel=0.0, abs=1e-9)


def test_geographic_legacy_from_outlet_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Check legacy outlet mode contract on deterministic synthetic inputs."""
    geo = _build_geographic_legacy_outlet_case(tmp_path, monkeypatch)

    outlet_path = Path(geo.geographic_path) / "outlet.shp"
    outlet_snap_path = Path(geo.geographic_path) / "outlet_snap.shp"
    watershed_tif_path = Path(geo.watershed)

    assert outlet_path.exists()
    assert outlet_snap_path.exists()
    assert watershed_tif_path.exists()
    assert Path(geo.watershed_shp).exists()
    assert float(geo.catch_area) > 0.0
    assert geo.catch_def == "from_outlet_coord"


def test_geographic_legacy_from_outlet_golden(
    update_goldens: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Freeze deterministic outlet-mode signature as non-regression baseline."""
    geo = _build_geographic_legacy_outlet_case(tmp_path, monkeypatch)
    actual = _legacy_signature(geo)

    if update_goldens:
        _write_json(GOLDEN_FILE_OUTLET, actual)
        return

    if not GOLDEN_FILE_OUTLET.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE_OUTLET}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_FILE_OUTLET)
    assert actual["shape_box_buff"] == expected["shape_box_buff"]
    assert actual["shape_buff"] == expected["shape_buff"]
    assert actual["shape_core"] == expected["shape_core"]
    assert actual["crs_proj"] == expected["crs_proj"]
    assert actual["dep_code"] == expected["dep_code"]

    for key in (
        "catch_area_km2",
        "dx",
        "dy",
        "xmin",
        "xmax",
        "ymin",
        "ymax",
        "mean_box_buff",
        "mean_core",
        "top_left_box_buff",
        "center_core",
    ):
        assert actual[key] == pytest.approx(expected[key], rel=0.0, abs=1e-9)


def test_geographic_config_rejects_missing_outlet_fields() -> None:
    """Validate model-level guardrails for outlet-based catchment definition."""
    with pytest.raises(ValueError, match="catch_def='from_outlet_coord' requires"):
        GeographicConfig(
            catch_def="from_outlet_coord",
            dem_init_path=Path("dummy_dem.tif"),
            snap_dist=50,
            buff_area=20.0,
        )


def test_geographic_legacy_missing_dem_file_raises(tmp_path: Path) -> None:
    """Legacy Geographic should fail early when input DEM does not exist."""
    catchment_path = tmp_path / "inputs" / "catchment.shp"
    _write_synthetic_catchment(catchment_path)
    missing_dem = tmp_path / "inputs" / "missing_dem.tif"

    cfg = GeographicConfig(
        catch_def="from_polyg_shp",
        dem_init_path=missing_dem,
        polyg_shp_path=catchment_path,
        buff_area=20.0,
        crs_project="EPSG:2154",
        dem_correc_type="breach",
    )
    initializing = SimpleNamespace(catch_folder=str(tmp_path / "case_missing_dem"))

    with pytest.raises(RasterioIOError):
        Geographic(config=cfg, initializing=initializing)


def test_resolve_dep_code_returns_none_when_geocoder_is_unavailable() -> None:
    """Department lookup is best-effort and should not fail offline runs."""
    assert (
        _resolve_dep_code(
            centroid_long_lat_Greenwich=[48.019638516018894, -2.8265621461935666],
            locator_factory=_UnavailableNominatim,
        )
        is None
    )
