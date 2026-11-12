"""An outlet gives its catchment through the terrain engine, a polygon is copied as given.

The Jenson part: two valleys side by side, the outlet two cells from the small floor
and five from the larger one. The window snap takes the largest accumulation and
jumps to the larger valley; the Jenson snap takes the nearest stream cell. The
surface is tie-free, so the answers are exact for both engines.
"""

import dataclasses
import logging
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from pydantic import ValidationError
from shapely.geometry import Point, box

from hydromodpy.catchment.algorithms.catchment_from_point import (
    CATCHMENT_LAYOUT,
    extract_catchment_from_point,
    extract_catchment_from_polygon,
    write_shapefile_without_duplicate_columns,
)
from hydromodpy.catchment.algorithms.flow_products import (
    TerrainRequest,
    build_regional_flow_products,
)
from hydromodpy.catchment.algorithms.geographic_paths import build_geographic_paths
from hydromodpy.catchment.algorithms.surface_from_dem import build_surface_topo_from_dem
from hydromodpy.catchment.preprocess.pipeline_steps import build_standard_catchment
from hydromodpy.catchment.terrain import registry
from hydromodpy.catchment.terrain.port import (
    LN_FLOAT32_COLLISION_COUNT,
    ConditioningExtent,
    JensonSnap,
    Outlet,
)
from hydromodpy.core.exceptions import (
    EmptyCatchmentError,
    TerrainProductError,
    TerrainRequestError,
)
from tests._helpers.geographic_cases import LAMBERT, outlet_config, read_band, write_features
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.terrain_doubles import fake_accumulation
from tests._helpers.whitebox_double import FakeVector, FakeWhiteboxBackend

POINT = "hydromodpy.catchment.algorithms.catchment_from_point"


def _extract(tmp_path: Path, accumulation, *, x=10.0, y=20.0, snap_dist=50, **options):
    options.setdefault("output_dir", tmp_path / "geo")
    return extract_catchment_from_point(
        x_outlet=x, y_outlet=y, snap_dist=snap_dist, accumulation=accumulation, **options
    )


def test_flat_layout() -> None:
    """The names are the contract: every golden in the tree reads them."""
    assert CATCHMENT_LAYOUT.per_outlet_directory is False
    assert (CATCHMENT_LAYOUT.mask_name, CATCHMENT_LAYOUT.boundary_name) == (
        "watershed.tif",
        "watershed.shp",
    )


def _empty_snap(backend, monkeypatch) -> None:
    monkeypatch.setattr(
        backend.delineation, "snap_pour_points_vector", lambda *a, **k: FakeVector(frame=[])
    )
    monkeypatch.setattr(backend.raster, "vector_record_count", lambda vector: 0)


def _empty_polygon(backend, monkeypatch) -> None:
    counts = iter([1, 0])
    monkeypatch.setattr(backend.raster, "write_raster", lambda raster, path: None)
    monkeypatch.setattr(backend.raster, "write_vector", lambda vector, path: None)
    monkeypatch.setattr(backend.raster, "vector_record_count", lambda vector: next(counts))
    monkeypatch.setattr(backend.delineation, "watershed_raster", lambda *a, **k: object())
    monkeypatch.setattr(
        backend.delineation, "raster_to_vector_polygons_raster", lambda r: FakeVector(frame=[])
    )
    monkeypatch.setattr(
        "hydromodpy.catchment.terrain.whitebox_engine.read_point", lambda path: (10.0, 20.0)
    )


@pytest.mark.parametrize(
    ("spoil", "error", "reason"),
    [
        (_empty_snap, TerrainProductError, "produced no feature"),
        # The engine knows rasters; only this layer knows the TOML keys.
        (_empty_snap, TerrainProductError, "geographic.catchment.snap_dist"),
        (_empty_polygon, EmptyCatchmentError, ""),
    ],
    ids=["empty snapped outlet", "names the keys to change", "empty watershed polygon"],
)
def test_refusals(monkeypatch, tmp_path, spoil, error, reason):
    for module in ("hydromodpy.catchment.terrain.whitebox_engine", POINT):
        monkeypatch.setattr(f"{module}.ensure_crs", lambda *a, **k: None)
    backend = FakeWhiteboxBackend()
    monkeypatch.setattr(backend.raster, "read_raster", lambda path: object())
    spoil(backend, monkeypatch)
    # A real ln accumulation: delineate reads it back to check float32 still orders it.
    acc = np.log(np.arange(1, 17, dtype="float32").reshape(4, 4))
    acc = write_geotiff(tmp_path / "acc.tif", acc, cell=25.0, nodata=-9999.0)
    accumulation = fake_accumulation(acc=acc, direc=tmp_path / "direc.tif")
    with pytest.raises(error, match=reason):
        _extract(tmp_path, accumulation, crs_project="EPSG:2154", backend=backend)


MOVED = "Outlet moved 131 m (limit 150 m) onto the flow network, from (389286, 6816519) to (389175, 6816450)."


# The threshold is half the allowed distance.
@pytest.mark.parametrize(
    ("distance_m", "level", "message"),
    [(130.54, logging.WARNING, MOVED), (75.0, logging.INFO, None)],
    ids=["long snap warns in one sentence", "short snap stays below the console"],
)
def test_snap_log_line(monkeypatch, tmp_path, caplog, distance_m, level, message) -> None:
    found = SimpleNamespace(
        mask_path=tmp_path / "watershed.tif",
        boundary_path=tmp_path / "watershed.shp",
        snapped_x=389175.004,
        snapped_y=6816449.6,
        snap_distance_m=distance_m,
    )
    engine = SimpleNamespace(delineate=lambda accumulation, outlets, **_: (found,))
    monkeypatch.setattr(
        f"{POINT}.terrain_registry.terrain_engines.create", lambda engine_id, backend=None: engine
    )
    monkeypatch.setattr(f"{POINT}.ensure_crs", lambda *a, **k: None)
    caplog.set_level(logging.INFO, logger="hydromodpy")
    accumulation = fake_accumulation(acc=tmp_path / "acc.tif", direc=tmp_path / "d.tif")
    products = _extract(
        tmp_path, accumulation, x=389285.91, y=6816518.749, snap_dist=150, crs_project="EPSG:2154"
    )
    assert products.snap_distance_m == distance_m
    (record,) = [r for r in caplog.records if r.getMessage().startswith("Outlet moved")]
    assert record.levelno == level
    assert message is None or record.getMessage() == message


@pytest.mark.parametrize(
    ("method", "threshold", "reason"),
    [
        ("nearest", None, "Unknown snap_method"),
        ("jenson", None, "stream_threshold_cells"),
        ("window", 100.0, "stream_threshold_cells"),
    ],
)
def test_refused_snap_and_threshold(tmp_path, method, threshold, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        _extract(
            tmp_path, fake_accumulation(), snap_method=method, stream_threshold_cells=threshold
        )


def test_given_polygon_copied(tmp_path) -> None:
    source = write_features(tmp_path / "given.shp", [box(0.0, 0.0, 100.0, 50.0)], name=["bv"])
    written = extract_catchment_from_polygon(
        polyg_shp_path=source, output_shp_path=tmp_path / "geo" / "watershed.shp"
    )
    copied = gpd.read_file(written)
    assert copied.geometry.iloc[0].area == pytest.approx(5000.0)
    assert copied["name"].tolist() == ["bv"]
    with pytest.raises(FileNotFoundError, match="polyg_shp_path"):
        extract_catchment_from_polygon(
            polyg_shp_path=tmp_path / "gone.shp", output_shp_path=written
        )


def test_surface_reads_the_dem(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", np.arange(6.0).reshape(2, 3), cell=10.0)
    assert build_surface_topo_from_dem(dem).name == "surface_topo"
    with pytest.raises(FileNotFoundError, match="DEM not found"):
        build_surface_topo_from_dem(tmp_path / "gone.tif")


def test_shapefile_columns_once(tmp_path, monkeypatch) -> None:
    frame = gpd.GeoDataFrame({"code": ["a", "b"]}, geometry=[Point(0, 0), Point(1, 1)], crs=LAMBERT)
    doubled = pd.concat([frame[["code"]], frame], axis=1)
    monkeypatch.setattr(gpd, "read_file", lambda path: gpd.GeoDataFrame(doubled))
    write_shapefile_without_duplicate_columns("ignored.shp", tmp_path / "out.shp")
    monkeypatch.undo()
    written = gpd.read_file(tmp_path / "out.shp")
    assert list(written.columns) == ["code", "geometry"]
    assert written["code"].tolist() == ["a", "b"]


RES, SIZE, CRS = 25.0, 41, "EPSG:2154"
SMALL_FLOOR, LARGE_FLOOR = 8, 15
LAST_SMALL_COLUMN = 11
"""The ridge sits between columns 11 and 12, so the small valley is columns 0 to 11."""
OUTLET_ROW, OUTLET_COL = 25, 10
SNAP_DISTANCE_M = 250.0
"""Five cells each side: the window holds both floors, at 2 and 5 cells."""
THRESHOLD_CELLS = 100.0
"""Above what a valley side accumulates, below what either floor does by row 8."""


def _write_two_valleys(path: Path) -> Path:
    rows, cols = np.mgrid[0:SIZE, 0:SIZE]
    walls = np.minimum(np.abs(cols - SMALL_FLOOR), np.abs(cols - LARGE_FLOOR))
    surface = (100.0 - rows * 0.5 + walls * 2.0).astype("float32")
    return write_geotiff(path, surface, cell=RES, nodata=-9999.0)


def _centre_x(col: int) -> float:
    return (col + 0.5) * RES


def _centre_y(row: int) -> float:
    return (SIZE - row - 0.5) * RES


@pytest.fixture(
    params=[
        "numpy_d8",
        # Whitebox fills depressions in a child interpreter.
        pytest.param(
            "whitebox_workflows",
            marks=[pytest.mark.allow_subprocess, pytest.mark.xdist_group(name="whitebox_backend")],
        ),
    ]
)
def engine(request):
    if request.param == "whitebox_workflows":
        pytest.importorskip("whitebox_workflows")
        from tests._helpers.whitebox import configure_whitebox_single_thread

        monkeypatch = pytest.MonkeyPatch()
        configure_whitebox_single_thread(monkeypatch)
        monkeypatch.undo()
    return registry.terrain_engines.create(request.param)


@pytest.fixture
def products(engine, tmp_path):
    """The chain a caller runs: condition, point, accumulate, draw the streams."""
    out = tmp_path / "out"
    dem = _write_two_valleys(tmp_path / "dem.tif")
    regional = ConditioningExtent.regional()
    conditioned = engine.condition_dem(
        dem, method="fill", extent=regional, out=out / "conditioned.tif"
    )
    directions = engine.drainage_directions(conditioned, out=out / "pointer.tif")
    accumulation = engine.flow_accumulation(
        directions, units="cells", transform="none", out=out / "acc.tif"
    )
    streams = engine.stream_network(accumulation, threshold=THRESHOLD_CELLS, out=out / "s.tif")
    return directions, accumulation, streams, out


def _delineate(engine, accumulation, out, *, snap, outlet=None):
    declared = Outlet(outlet_id="declared", x=_centre_x(OUTLET_COL), y=_centre_y(OUTLET_ROW))
    (catchment,) = engine.delineate(
        accumulation,
        [outlet or declared],
        out_dir=out / "catchment",
        snap_distance_m=SNAP_DISTANCE_M,
        snap=snap,
    )
    return catchment, np.unique(np.nonzero(read_band(catchment.mask_path) == 1)[1])


def test_window_snap(engine, products) -> None:
    """The failure the Jenson snap exists for, measured."""
    _directions, accumulation, _streams, out = products
    catchment, columns = _delineate(engine, accumulation, out, snap="window")
    assert catchment.snapped_x == pytest.approx(_centre_x(LARGE_FLOOR))
    assert catchment.cell_count == (SIZE - LAST_SMALL_COLUMN - 1) * (OUTLET_ROW + 5 + 1)
    assert columns.min() > LAST_SMALL_COLUMN


def test_jenson_snap(engine, products) -> None:
    """A transformed accumulation is not read, so the window snap's refusals do not apply."""
    directions, accumulation, streams, out = products
    transformed = engine.flow_accumulation(
        directions, units="m2", transform="ln", out=out / "acc_ln_m2.tif"
    )
    catchment, columns = _delineate(engine, accumulation, out, snap=JensonSnap(streams=streams))
    on_ln, _ = _delineate(engine, transformed, out, snap=JensonSnap(streams=streams))
    assert catchment.snapped_x == on_ln.snapped_x == pytest.approx(_centre_x(SMALL_FLOOR))
    assert catchment.snapped_y == pytest.approx(_centre_y(OUTLET_ROW))
    assert catchment.snap_distance_m == pytest.approx(2 * RES)
    assert catchment.cell_count == (LAST_SMALL_COLUMN + 1) * (OUTLET_ROW + 1)
    assert columns.max() <= LAST_SMALL_COLUMN


def test_refused_snap(engine, products) -> None:
    """Never delineate from a hillside cell: the catchment would be a few cells."""
    directions, accumulation, streams, out = products
    far_from_both = Outlet(outlet_id="far", x=_centre_x(28), y=_centre_y(OUTLET_ROW))
    elsewhere = dataclasses.replace(directions, path=out / "another_pointer.tif")
    other = dataclasses.replace(streams, directions=elsewhere)
    jenson = JensonSnap(streams=streams)
    with pytest.raises(TerrainProductError, match="no cell of the stream network"):
        _delineate(engine, accumulation, out, snap=jenson, outlet=far_from_both)
    with pytest.raises(TerrainProductError, match="another pointer"):
        _delineate(engine, accumulation, out, snap=JensonSnap(streams=other))
    with pytest.raises(TerrainRequestError, match="Unknown snap method"):
        _delineate(engine, accumulation, out, snap="nearest")


def _outlet_config(snap_method: str = "window", **overrides):
    return outlet_config(
        x=_centre_x(OUTLET_COL),
        y=_centre_y(OUTLET_ROW),
        catchment={"snap_dist": SNAP_DISTANCE_M, "snap_method": snap_method},
        terrain_engine="numpy_d8",
        **overrides,
    )


def _terrain_key(config, method: str = "fill") -> str:
    """The terrain product key one config asks for, over a never-read DEM."""
    from hydromodpy.catchment.algorithms.terrain_stored import SCHEMA_VERSION
    from hydromodpy.results.products.key import product_key

    engine = registry.terrain_engines.get(config.terrain_engine)
    request = TerrainRequest(
        dem=Path("dem.tif"),
        dem_sha256="a" * 64,
        state="raw",
        method=method,
        capped_breach=None,
        crs_project=config.crs_project,
        engine={"engine_id": engine.engine_id, "engine_version": engine.engine_version},
        notched=False,
        out_dir=Path("out"),
    )
    return product_key(
        "terrain",
        codec=SCHEMA_VERSION,
        package="catchment",
        inputs={"dem": request.dem_sha256, "dem_state": request.state},
        processing=request.processing(),
        engine=request.engine,
    )


def test_config_defaults() -> None:
    window = _outlet_config()
    jenson = _outlet_config("jenson", river_network={"threshold_area_km2": 0.5})
    assert (window.snap_method, jenson.snap_method) == ("window", "jenson")
    assert jenson.river_network.enabled is False
    with pytest.raises(ValidationError, match="threshold_area_km2"):
        _outlet_config("jenson")
    with pytest.raises(ValidationError, match="snap_method"):
        _outlet_config("nearest")
    # The snap draws the catchment, not the terrain: a window and a jenson config
    # read the same key, and only the conditioning method moves it.
    assert _terrain_key(window) == _terrain_key(jenson)
    assert _terrain_key(window) != _terrain_key(window, "breach")


def test_pipeline_snap_on_network(tmp_path) -> None:
    """The threshold is read in km2 and turned into cells on the grid of the routing."""
    paths = build_geographic_paths(tmp_path / "geographic_run")
    flow = build_regional_flow_products(
        dem_path=_write_two_valleys(tmp_path / "dem.tif"),
        dem_out_dir_path=paths.correcflow_path,
        dem_correc_type="fill",
        crs_project=CRS,
        engine_id="numpy_d8",
    )
    area_km2 = THRESHOLD_CELLS * RES * RES / 1.0e6
    jenson = _outlet_config("jenson", river_network={"threshold_area_km2": area_km2})
    options = dict(paths=paths, accumulation=flow.accumulation, crs_project=CRS, backend=object())
    on_window = build_standard_catchment(config=_outlet_config(), **options)
    on_jenson = build_standard_catchment(config=jenson, **options)
    assert on_window.x_outlet_snapped == pytest.approx(_centre_x(LARGE_FLOOR))
    assert on_jenson.x_outlet_snapped == pytest.approx(_centre_x(SMALL_FLOOR))
    assert on_jenson.snap_distance_m == pytest.approx(2 * RES)


@pytest.mark.allow_subprocess
def test_basin_above_float32_bound(tmp_path) -> None:
    """The accumulation is stored as ln in float32, which cannot order counts above
    1 049 558 cells, so the snap window is ranked on raw counts."""
    size = 1100  # 1.21 M cells, above the float32 ln bound.
    assert size * size > LN_FLOAT32_COLLISION_COUNT
    rows, cols = np.mgrid[0:size, 0:size]
    surface = (500.0 - 0.5 * rows - 0.4 * cols).astype("float32")
    dem = write_geotiff(tmp_path / "dem.tif", surface, cell=5.0, nodata=-9999.0)
    flow = build_regional_flow_products(
        dem_path=dem, dem_out_dir_path=tmp_path / "flow", dem_correc_type="fill"
    )
    corner = dict(x=(size - 0.5) * 5.0, y=0.5 * 5.0, snap_dist=10)
    out = _extract(tmp_path, flow.accumulation, **corner, output_dir=tmp_path / "catchment")
    with rasterio.open(out.watershed_tif) as src:
        mask, nodata = src.read(1), src.nodata
    assert int(np.count_nonzero((mask != nodata) & (mask > 0))) > LN_FLOAT32_COLLISION_COUNT
