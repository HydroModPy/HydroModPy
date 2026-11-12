"""Whitebox facade on a 4 x 4 DEM slope (m): its three tool groups, stdio handling and file outputs.

The facade splits into raster, flow and delineation tools. Each tool reads and writes
GeoTIFF or shapefile files, or works on in-memory Whitebox objects.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import LineString, Point, box

import hydromodpy.catchment.delineation as delineation_pkg
from hydromodpy.catchment.delineation import get_whitebox_backend
from hydromodpy.catchment.delineation import whitebox_workflows_backend as wbw_backend
from hydromodpy.catchment.delineation.whitebox_workflows_backend import WhiteboxWorkflowsBackend
from tests._helpers.geotiffs import write_geotiff

# The whitebox_workflows native binding is not safe under pytest-xdist fork
# distribution. Keep every test in this module on the same worker.
pytestmark = pytest.mark.xdist_group(name="whitebox_backend")

# Elevation in m, draining to the north-east corner.
SLOPE = np.array(
    [
        [10.0, 9.0, 8.0, 7.0],
        [11.0, 10.0, 9.0, 8.0],
        [12.0, 11.0, 10.0, 9.0],
        [13.0, 12.0, 11.0, 10.0],
    ],
    dtype=np.float32,
)

SHAPES = {
    "polygon": box(0.0, 0.0, 3.0, 4.0),
    "points": Point(1.5, 2.5),
    "lines": LineString([(0.5, 3.5), (2.5, 0.5)]),
}


def write_slope_raster(path: Path, data: np.ndarray) -> Path:
    return write_geotiff(path, data, origin=(0.0, float(data.shape[0])), nodata=-9999.0)


def read_raster(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1, masked=True).astype(float).filled(np.nan)


def count_active_cells(path: Path) -> int:
    values = read_raster(path)
    return int(np.count_nonzero(np.isfinite(values) & (values > 0)))


@pytest.fixture
def slope(tmp_path: Path) -> SimpleNamespace:
    """The DEM file plus a polygon, a point and a line shapefile over it."""
    layers = SimpleNamespace(dem=write_slope_raster(tmp_path / "dem.tif", SLOPE))
    for name, geometry in SHAPES.items():
        path = tmp_path / f"{name}.shp"
        gpd.GeoDataFrame({"id": [1]}, geometry=[geometry], crs="EPSG:2154").to_file(path)
        setattr(layers, name, path)
    return layers


SURFACES = [
    pytest.param(
        "WhiteboxRasterBackend",
        ("read_raster", "write_raster", "clip_raster_to_polygon"),
        id="raster",
    ),
    pytest.param(
        "WhiteboxFlowBackend",
        ("fill_depressions", "breach_depressions", "d8_pointer", "d8_flow_accumulation"),
        id="flow",
    ),
    pytest.param(
        "WhiteboxDelineationBackend",
        ("watershed", "extract_streams", "snap_pour_points"),
        id="delineation",
    ),
]


@pytest.mark.parametrize(("class_name", "methods"), SURFACES)
def test_tool_group_surface(class_name, methods):
    group = getattr(wbw_backend, class_name)
    assert all(callable(getattr(group, method)) for method in methods)


def test_facade_holds_three_groups():
    backend = WhiteboxWorkflowsBackend()
    assert isinstance(backend.raster, wbw_backend.WhiteboxRasterBackend)
    assert isinstance(backend.flow, wbw_backend.WhiteboxFlowBackend)
    assert isinstance(backend.delineation, wbw_backend.WhiteboxDelineationBackend)


RETIRED_NAMES = [
    pytest.param(lambda: delineation_pkg.WhiteboxToolsBackend, AttributeError, None, id="alias"),
    pytest.param(
        lambda: importlib.import_module("hydromodpy.catchment.delineation.whitebox_tools_backend"),
        ModuleNotFoundError,
        None,
        id="module",
    ),
    pytest.param(
        lambda: get_whitebox_backend("whitebox"), TypeError, "positional argument", id="selector"
    ),
]


@pytest.mark.parametrize(("load", "error", "match"), RETIRED_NAMES)
def test_retired_names_are_gone(load, error, match):
    sys.modules.pop("hydromodpy.catchment.delineation.whitebox_tools_backend", None)
    with pytest.raises(error, match=match):
        load()


def noisy_native_operation():
    os.write(1, b"native-stdout\n")
    os.write(2, b"native-stderr\n")
    print("python-stdout")
    return 123


def no_descriptor_left(fd):
    raise OSError("no descriptor left")


STDIO_VARIABLE = "HMP_WHITEBOX_REDIRECT_NATIVE_STDIO"

# fd 2 is always left alone, it carries the live progress display.
STDIO = [
    pytest.param(STDIO_VARIABLE, "1", False, "", id="fd redirect"),
    pytest.param(STDIO_VARIABLE, "1", True, "native-stdout\n", id="fd redirect without dup"),
    pytest.param(STDIO_VARIABLE, None, False, "native-stdout\n", id="pytest default"),
    pytest.param(
        "HMP_WHITEBOX_VERBOSE", "yes", False, "native-stdout\npython-stdout\n", id="verbose"
    ),
]


@pytest.mark.parametrize(("variable", "value", "dup_fails", "out"), STDIO)
def test_native_stdout_silencing(capfd, monkeypatch, variable, value, dup_fails, out):
    monkeypatch.delenv(variable, raising=False)
    if value is not None:
        monkeypatch.setenv(variable, value)
    backend = WhiteboxWorkflowsBackend()
    if dup_fails:
        # Only the module's view of ``os``, pytest's own capture needs ``os.dup``.
        failing_os = SimpleNamespace(**{**vars(os), "dup": no_descriptor_left})
        monkeypatch.setattr(wbw_backend.raster, "os", failing_os)

    assert backend.raster.run_env_operation(noisy_native_operation) == 123
    captured = capfd.readouterr()
    assert captured.out == out
    assert captured.err == "native-stderr\n"


RECORD_COUNTS = [
    pytest.param(None, None, id="no records"),
    pytest.param([1, 2], 2, id="list"),
    pytest.param((record for record in "abc"), 3, id="iterator"),
    pytest.param(object(), None, id="not iterable"),
]


@pytest.mark.parametrize(("records", "count"), RECORD_COUNTS)
def test_vector_record_count(records, count):
    raster = WhiteboxWorkflowsBackend().raster
    assert raster.vector_record_count(SimpleNamespace(records=records)) == count


def test_empty_vector_write_refused(tmp_path):
    raster = WhiteboxWorkflowsBackend().raster
    with pytest.raises(ValueError, match="empty vector layer"):
        raster.write_vector(SimpleNamespace(records=[]), str(tmp_path / "empty.shp"))


def test_raster_compression_on_request(slope, tmp_path):
    backend = WhiteboxWorkflowsBackend()
    raster = backend.raster.read_raster(str(slope.dem))
    for enabled in (False, True):
        backend.raster.set_compress_rasters(enabled)
        backend.raster.write_raster(raster, str(tmp_path / f"{enabled}.tif"))
        with rasterio.open(tmp_path / f"{enabled}.tif") as src:
            assert (src.compression is not None) is enabled
            np.testing.assert_array_equal(src.read(1), SLOPE)


SMOKE_OUTPUTS = [
    "dem_fill.tif",
    "dem_breach.tif",
    "dem_direc.tif",
    "dem_acc.tif",
    "dem_acc_cells.tif",
    "dem_clip.tif",
    "points_clip.shp",
    "points_snap.shp",
    "watershed.tif",
    "watershed.shp",
    "watershed_lines.shp",
    "points.tif",
    "lines.tif",
    "poly.tif",
    "lines_nodata.tif",
    "trace.tif",
    "downslope.tif",
    "mass_flux.tif",
    "streams.tif",
    "streams_pruned.tif",
    "streams.shp",
    "streams_order.tif",
    "streams_link_id.tif",
    "dissolved.shp",
]


@pytest.mark.allow_subprocess  # depression removal runs in a child
def test_tools_run_on_files(slope, tmp_path):
    backend = get_whitebox_backend()
    dem, polygon, points, lines = map(str, (slope.dem, slope.polygon, slope.points, slope.lines))
    out = {
        name.replace(".tif", "").replace(".shp", "_shp"): str(tmp_path / name)
        for name in SMOKE_OUTPUTS
    }

    backend.flow.fill_depressions(dem, out["dem_fill"])
    backend.flow.breach_depressions(dem, out["dem_breach"])
    backend.flow.d8_pointer(out["dem_fill"], out["dem_direc"])
    backend.flow.d8_flow_accumulation(out["dem_fill"], out["dem_acc"], log=True)
    backend.flow.d8_flow_accumulation(out["dem_fill"], out["dem_acc_cells"], log=False)
    backend.delineation.extract_streams(
        out["dem_acc_cells"], out["streams"], threshold=1, zero_background=True
    )
    backend.delineation.remove_short_streams(
        out["dem_direc"], out["streams"], out["streams_pruned"], min_length=0
    )
    backend.delineation.strahler_stream_order(
        out["dem_direc"], out["streams_pruned"], out["streams_order"], zero_background=True
    )
    backend.delineation.stream_link_identifier(
        out["dem_direc"], out["streams_pruned"], out["streams_link_id"], zero_background=True
    )
    backend.delineation.raster_streams_to_vector(
        out["streams_pruned"], out["dem_direc"], out["streams_shp"], all_vertices=False
    )
    backend.raster.clip_raster_to_polygon(
        out["dem_fill"], polygon, out["dem_clip"], maintain_dimensions=False
    )
    backend.raster.clip(points, polygon, out["points_clip_shp"])
    backend.delineation.snap_pour_points(points, out["dem_acc"], out["points_snap_shp"], 2)
    backend.delineation.watershed(out["dem_direc"], out["points_snap_shp"], out["watershed"])
    backend.delineation.raster_to_vector_polygons(out["watershed"], out["watershed_shp"])
    backend.delineation.polygons_to_lines(out["watershed_shp"], out["watershed_lines_shp"])
    backend.raster.dissolve(out["watershed_shp"], out["dissolved_shp"])
    backend.raster.vector_points_to_raster(points, out["points"], field="id", base=out["dem_fill"])
    backend.raster.vector_lines_to_raster(lines, out["lines"], field="id", base=out["dem_fill"])
    backend.raster.vector_polygons_to_raster(polygon, out["poly"], field="id", base=out["dem_fill"])
    backend.raster.set_nodata_value(out["lines"], out["lines_nodata"], back_value=-32768)
    backend.raster.polygon_area(out["watershed_shp"])
    backend.delineation.raster_to_vector_points(out["points"], str(tmp_path / "point_pixels.shp"))
    backend.flow.trace_downslope_flowpaths(points, out["dem_direc"], out["trace"])
    backend.flow.downslope_distance_to_stream(out["dem_fill"], out["points"], out["downslope"])
    backend.delineation.add_point_coordinates_to_table(out["points_clip_shp"])
    backend.raster.extract_raster_values_at_points(out["points"], out["points_clip_shp"])
    efficiency = write_slope_raster(tmp_path / "eff.tif", np.ones((4, 4), dtype=np.float32))
    absorption = write_slope_raster(tmp_path / "abs.tif", np.zeros((4, 4), dtype=np.float32))
    backend.flow.d8_mass_flux(
        out["dem_fill"], out["points"], str(efficiency), str(absorption), out["mass_flux"]
    )

    assert all(Path(path).exists() for path in out.values())
    assert "AREA" in set(gpd.read_file(out["watershed_shp"]).columns)
    assert {"XCOORD", "YCOORD", "VALUE1"} <= set(gpd.read_file(out["points_clip_shp"]).columns)
    assert len(gpd.read_file(out["dissolved_shp"])) == 1
    n_streams = count_active_cells(out["streams"])
    assert 0 < count_active_cells(out["streams_pruned"]) <= n_streams
    assert count_active_cells(out["streams_order"]) > 0
    assert count_active_cells(out["streams_link_id"]) > 0
    assert not gpd.read_file(out["streams_shp"]).empty


# Each row is (group, tool, input products, default keyword). Giving the default
# explicitly must change nothing, because options are only passed on when given.
EXPLICIT_DEFAULTS = [
    ("delineation", "strahler_stream_order", ("direc", "streams"), {"esri_pntr": False}),
    ("delineation", "stream_link_identifier", ("direc", "streams"), {"esri_pntr": False}),
    ("delineation", "remove_short_streams", ("direc", "streams"), {"esri_pntr": False}),
    ("flow", "downslope_distance_to_stream", ("fill", "streams"), {"use_dinf": False}),
]


@pytest.mark.allow_subprocess  # depression removal runs in a child
def test_explicit_defaults_change_nothing(slope, tmp_path):
    backend = WhiteboxWorkflowsBackend()
    product = {name: str(tmp_path / f"{name}.tif") for name in ("fill", "direc", "acc", "streams")}
    backend.flow.fill_depressions(str(slope.dem), product["fill"])
    backend.flow.d8_pointer(product["fill"], product["direc"])
    backend.flow.d8_flow_accumulation(product["fill"], product["acc"], log=False)
    backend.delineation.extract_streams(product["acc"], product["streams"], threshold=1)

    for group, tool, inputs, defaults in EXPLICIT_DEFAULTS:
        call = getattr(getattr(backend, group), tool)
        args = [product[name] for name in inputs]
        left, spelled = tmp_path / f"{tool}_left.tif", tmp_path / f"{tool}_spelled.tif"
        call(*args, str(left))
        call(*args, str(spelled), **defaults)
        np.testing.assert_array_equal(read_raster(left), read_raster(spelled))

    backend.delineation.raster_streams_to_vector(
        product["streams"], product["direc"], str(tmp_path / "s.shp"), esri_pointer=False
    )
    assert not gpd.read_file(tmp_path / "s.shp").empty
    backend.delineation.extract_streams(product["acc"], str(tmp_path / "default.tif"))
    assert (tmp_path / "default.tif").exists()


def test_points_rasterized_on_dem_grid(slope, tmp_path):
    # A single point has no extent of its own, so it is rasterized on the DEM grid.
    backend = WhiteboxWorkflowsBackend()
    backend.raster.vector_points_to_raster(
        str(slope.points),
        str(tmp_path / "out.tif"),
        field="id",
        zero_background=True,
        base=str(slope.dem),
        assign_op="last",
    )
    values = read_raster(tmp_path / "out.tif")
    assert np.isfinite(values).all()
    assert 1.0 in values and set(np.unique(values)) <= {0.0, 1.0}


@pytest.mark.parametrize(
    ("method", "shape"),
    [("vector_lines_to_raster", "lines"), ("vector_polygons_to_raster", "polygon")],
)
def test_zero_background_has_no_nodata(slope, tmp_path, method, shape):
    backend = WhiteboxWorkflowsBackend()
    rasterize = getattr(backend.raster, method)
    rasterize(
        str(getattr(slope, shape)),
        str(tmp_path / "out.tif"),
        field="id",
        zero_background=True,
        cell_size=0.5,
    )
    values = read_raster(tmp_path / "out.tif")
    assert np.isfinite(values).all()
    assert 1.0 in values and set(np.unique(values)) <= {0.0, 1.0}


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason="WhiteboxRasterBackend.clip sends a raster to env.clip, which takes vectors only",
)
def test_clip_raster_to_polygon(slope, tmp_path):
    raster = WhiteboxWorkflowsBackend().raster
    raster.clip(str(slope.dem), str(slope.polygon), str(tmp_path / "box.tif"))
    assert np.nanmax(read_raster(tmp_path / "box.tif")) <= SLOPE.max()


def test_nodata_changed_in_place(slope):
    WhiteboxWorkflowsBackend().raster.modify_no_data_value(str(slope.dem), new_value=-1.0)
    with rasterio.open(slope.dem) as src:
        assert src.nodata == -1.0
        np.testing.assert_array_equal(src.read(1), SLOPE)


@pytest.mark.allow_subprocess  # depression removal runs in a child
def test_tools_run_in_memory(slope, tmp_path):
    backend = get_whitebox_backend()
    flow, delineation, raster = backend.flow, backend.delineation, backend.raster

    dem_fill = flow.fill_depressions_raster(raster.read_raster(str(slope.dem)))
    direc = flow.d8_pointer_raster(dem_fill)
    acc = flow.d8_flow_accumulation_raster(dem_fill, log=True)
    points_snap = delineation.snap_pour_points_vector(raster.read_vector(str(slope.points)), acc, 2)
    streams = delineation.extract_streams_raster(
        flow.d8_flow_accumulation_raster(dem_fill), threshold=1
    )
    on_stream = delineation.jenson_snap_pour_points_vector(
        raster.read_vector(str(slope.points)), streams, 2
    )
    assert raster.vector_record_count(on_stream) == 1
    watershed = delineation.watershed_raster(direc, points_snap)
    watershed_poly = delineation.raster_to_vector_polygons_raster(watershed)
    clipped = raster.clip_raster_to_polygon_raster(
        dem_fill, raster.read_vector(str(slope.polygon)), maintain_dimensions=False
    )
    raster.write_raster(clipped, str(tmp_path / "clipped.tif"))
    raster.write_vector(watershed_poly, str(tmp_path / "watershed_mem.shp"))

    assert (tmp_path / "clipped.tif").exists()
    assert (tmp_path / "watershed_mem.shp").exists()
