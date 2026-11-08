"""The Whitebox facade: its selection, its stdio handling and its tools on a 4 x 4 slope."""

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
from hydromodpy.catchment.delineation import clear_whitebox_backend_cache, get_whitebox_backend
from hydromodpy.catchment.delineation import whitebox_workflows_backend as wbw_backend
from hydromodpy.catchment.delineation.whitebox_workflows_backend import WhiteboxWorkflowsBackend
from tests._helpers.geotiffs import write_geotiff

# The whitebox_workflows native binding is not safe under pytest-xdist fork
# distribution. Keep every test in this module on the same worker.
pytestmark = pytest.mark.xdist_group(name="whitebox_backend")

SLOPE = np.array(
    [[10.0, 9.0, 8.0, 7.0], [11.0, 10.0, 9.0, 8.0], [12.0, 11.0, 10.0, 9.0], [13.0, 12.0, 11.0, 10.0]],
    dtype=np.float32,
)  # fmt: skip


def _write_raster(path: Path, data: np.ndarray) -> Path:
    return write_geotiff(path, data, origin=(0.0, float(data.shape[0])), nodata=-9999.0)


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1, masked=True).astype(float).filled(np.nan)


def _count_active_cells(path: Path) -> int:
    values = _read(path)
    return int(np.count_nonzero(np.isfinite(values) & (values > 0)))


@pytest.fixture
def slope(tmp_path: Path) -> SimpleNamespace:
    """A 4 x 4 slope draining north-east, a box polygon, one point and one line."""
    layers = SimpleNamespace(dem=_write_raster(tmp_path / "dem.tif", SLOPE))
    shapes = {"polygon": box(0.0, 0.0, 3.0, 4.0), "points": Point(1.5, 2.5), "lines": LineString([(0.5, 3.5), (2.5, 0.5)])}  # fmt: skip
    for name, geometry in shapes.items():
        setattr(layers, name, tmp_path / f"{name}.shp")
        gpd.GeoDataFrame({"id": [1]}, geometry=[geometry], crs="EPSG:2154").to_file(getattr(layers, name))  # fmt: skip
    return layers


def test_two_calls_return_the_one_backend_until_the_cache_is_cleared():
    clear_whitebox_backend_cache()
    backend = get_whitebox_backend()
    assert isinstance(backend, WhiteboxWorkflowsBackend)
    assert get_whitebox_backend() is backend
    clear_whitebox_backend_cache()
    assert get_whitebox_backend() is not backend


def test_the_package_exposes_the_three_thematic_backends():
    """The production surface: ``raster``, ``flow`` and ``delineation`` of the facade."""
    surfaces = {
        "WhiteboxRasterBackend": ("read_raster", "write_raster", "clip_raster_to_polygon"),
        "WhiteboxFlowBackend": ("fill_depressions", "breach_depressions", "d8_pointer", "d8_flow_accumulation"),
        "WhiteboxDelineationBackend": ("watershed", "extract_streams", "snap_pour_points"),
    }  # fmt: skip
    for name, methods in surfaces.items():
        cls = getattr(wbw_backend, name)
        assert all(callable(getattr(cls, method)) for method in methods)
    backend = WhiteboxWorkflowsBackend()
    assert isinstance(backend.raster, wbw_backend.WhiteboxRasterBackend)
    assert isinstance(backend.flow, wbw_backend.WhiteboxFlowBackend)
    assert isinstance(backend.delineation, wbw_backend.WhiteboxDelineationBackend)


@pytest.mark.parametrize(
    ("load", "error", "match"),
    [
        (lambda: delineation_pkg.WhiteboxToolsBackend, AttributeError, None),
        (lambda: importlib.import_module("hydromodpy.catchment.delineation.whitebox_tools_backend"), ModuleNotFoundError, None),
        (lambda: get_whitebox_backend("whitebox"), TypeError, "positional argument"),
    ],
    ids=["whitebox_tools_alias", "whitebox_tools_backend_module", "backend_selector_argument"],
)  # fmt: skip
def test_a_retired_whitebox_tools_name_is_gone(load, error, match):
    sys.modules.pop("hydromodpy.catchment.delineation.whitebox_tools_backend", None)
    with pytest.raises(error, match=match):
        load()


def _noisy_native_operation():
    os.write(1, b"native-stdout\n")
    os.write(2, b"native-stderr\n")
    print("python-stdout")
    return 123


@pytest.mark.parametrize(
    ("variable", "value", "dup_fails", "out"),
    [
        ("HMP_WHITEBOX_REDIRECT_NATIVE_STDIO", "1", False, ""),
        ("HMP_WHITEBOX_REDIRECT_NATIVE_STDIO", "1", True, "native-stdout\n"),
        ("HMP_WHITEBOX_REDIRECT_NATIVE_STDIO", None, False, "native-stdout\n"),
        ("HMP_WHITEBOX_VERBOSE", "yes", False, "native-stdout\npython-stdout\n"),
    ],
    ids=["fd_redirect", "fd_redirect_without_dup", "pytest_default_python_only", "verbose"],
)
def test_whitebox_native_stdout_is_silenced_as_configured(
    capfd, monkeypatch, variable, value, dup_fails, out
):
    """fd 2 is always left alone: it carries the live progress display."""
    monkeypatch.delenv(variable, raising=False)
    if value is not None:
        monkeypatch.setenv(variable, value)
    backend = WhiteboxWorkflowsBackend()
    if dup_fails:
        # Only the module's view of ``os``: pytest's own capture needs ``os.dup``.
        def no_descriptor_left(fd):
            raise OSError("no descriptor left")

        monkeypatch.setattr(
            wbw_backend.raster, "os", SimpleNamespace(**{**vars(os), "dup": no_descriptor_left})
        )

    assert backend.raster.run_env_operation(_noisy_native_operation) == 123
    captured = capfd.readouterr()
    assert captured.out == out
    assert captured.err == "native-stderr\n"


@pytest.mark.parametrize(
    ("records", "count"),
    [(None, None), ([1, 2], 2), ((record for record in "abc"), 3), (object(), None)],
    ids=["no_records", "a_list", "an_iterator", "not_iterable"],
)
def test_the_record_count_of_a_vector_is_read_however_its_records_come(records, count):
    raster = WhiteboxWorkflowsBackend().raster
    assert raster.vector_record_count(SimpleNamespace(records=records)) == count


def test_whitebox_workflows_backend_rejects_empty_vector_write(tmp_path: Path):
    raster = WhiteboxWorkflowsBackend().raster
    with pytest.raises(ValueError, match="empty vector layer"):
        raster.write_vector(SimpleNamespace(records=[]), str(tmp_path / "empty.shp"))


def test_a_raster_is_written_compressed_only_when_asked(slope, tmp_path: Path):
    backend = WhiteboxWorkflowsBackend()
    raster = backend.raster.read_raster(str(slope.dem))
    for enabled in (False, True):
        backend.raster.set_compress_rasters(enabled)
        backend.raster.write_raster(raster, str(tmp_path / f"{enabled}.tif"))
        with rasterio.open(tmp_path / f"{enabled}.tif") as src:
            assert (src.compression is not None) is enabled
            np.testing.assert_array_equal(src.read(1), SLOPE)


@pytest.mark.allow_subprocess  # depression removal runs in a child
def test_whitebox_workflows_backend_smoke_operations(slope, tmp_path: Path):
    backend = get_whitebox_backend()
    dem, polygon, points, lines = (str(slope.dem), str(slope.polygon), str(slope.points), str(slope.lines))  # fmt: skip
    names = """dem_fill.tif dem_breach.tif dem_direc.tif dem_acc.tif dem_acc_cells.tif dem_clip.tif
        points_clip.shp points_snap.shp watershed.tif watershed.shp watershed_lines.shp points.tif
        lines.tif poly.tif lines_nodata.tif trace.tif downslope.tif mass_flux.tif streams.tif
        streams_pruned.tif streams.shp streams_order.tif streams_link_id.tif dissolved.shp"""
    o = {n.replace(".tif", "").replace(".shp", "_shp"): str(tmp_path / n) for n in names.split()}

    backend.flow.fill_depressions(dem, o["dem_fill"])
    backend.flow.breach_depressions(dem, o["dem_breach"])
    backend.flow.d8_pointer(o["dem_fill"], o["dem_direc"])
    backend.flow.d8_flow_accumulation(o["dem_fill"], o["dem_acc"], log=True)
    backend.flow.d8_flow_accumulation(o["dem_fill"], o["dem_acc_cells"], log=False)
    backend.delineation.extract_streams(
        o["dem_acc_cells"], o["streams"], threshold=1, zero_background=True
    )
    backend.delineation.remove_short_streams(
        o["dem_direc"], o["streams"], o["streams_pruned"], min_length=0
    )
    backend.delineation.strahler_stream_order(o["dem_direc"], o["streams_pruned"], o["streams_order"], zero_background=True)  # fmt: skip
    backend.delineation.stream_link_identifier(o["dem_direc"], o["streams_pruned"], o["streams_link_id"], zero_background=True)  # fmt: skip
    backend.delineation.raster_streams_to_vector(o["streams_pruned"], o["dem_direc"], o["streams_shp"], all_vertices=False)  # fmt: skip
    backend.raster.clip_raster_to_polygon(
        o["dem_fill"], polygon, o["dem_clip"], maintain_dimensions=False
    )
    backend.raster.clip(points, polygon, o["points_clip_shp"])
    backend.delineation.snap_pour_points(points, o["dem_acc"], o["points_snap_shp"], 2)
    backend.delineation.watershed(o["dem_direc"], o["points_snap_shp"], o["watershed"])
    backend.delineation.raster_to_vector_polygons(o["watershed"], o["watershed_shp"])
    backend.delineation.polygons_to_lines(o["watershed_shp"], o["watershed_lines_shp"])
    backend.raster.dissolve(o["watershed_shp"], o["dissolved_shp"])
    backend.raster.vector_points_to_raster(points, o["points"], field="id", base=o["dem_fill"])
    backend.raster.vector_lines_to_raster(lines, o["lines"], field="id", base=o["dem_fill"])
    backend.raster.vector_polygons_to_raster(polygon, o["poly"], field="id", base=o["dem_fill"])
    backend.raster.set_nodata_value(o["lines"], o["lines_nodata"], back_value=-32768)
    backend.raster.polygon_area(o["watershed_shp"])
    backend.delineation.raster_to_vector_points(o["points"], str(tmp_path / "point_pixels.shp"))
    backend.flow.trace_downslope_flowpaths(points, o["dem_direc"], o["trace"])
    backend.flow.downslope_distance_to_stream(o["dem_fill"], o["points"], o["downslope"])
    backend.delineation.add_point_coordinates_to_table(o["points_clip_shp"])
    backend.raster.extract_raster_values_at_points(o["points"], o["points_clip_shp"])
    eff = _write_raster(tmp_path / "eff.tif", np.ones((4, 4), dtype=np.float32))
    absr = _write_raster(tmp_path / "abs.tif", np.zeros((4, 4), dtype=np.float32))
    backend.flow.d8_mass_flux(o["dem_fill"], o["points"], str(eff), str(absr), o["mass_flux"])

    assert all(Path(path).exists() for path in o.values())
    assert "AREA" in set(gpd.read_file(o["watershed_shp"]).columns)
    assert {"XCOORD", "YCOORD", "VALUE1"} <= set(gpd.read_file(o["points_clip_shp"]).columns)
    assert len(gpd.read_file(o["dissolved_shp"])) == 1
    streams = _count_active_cells(o["streams"])
    assert 0 < _count_active_cells(o["streams_pruned"]) <= streams
    assert _count_active_cells(o["streams_order"]) > 0
    assert _count_active_cells(o["streams_link_id"]) > 0
    assert not gpd.read_file(o["streams_shp"]).empty


@pytest.mark.allow_subprocess  # depression removal runs in a child
def test_the_defaults_spelled_out_give_the_products_left_to_whitebox(slope, tmp_path: Path):
    """Every optional argument is only passed on when given; giving the default changes nothing."""
    backend = WhiteboxWorkflowsBackend()
    t = {name: str(tmp_path / f"{name}.tif") for name in ("fill", "direc", "acc", "streams", "a", "b", "c", "d", "e", "f", "g", "h")}  # fmt: skip
    backend.flow.fill_depressions(str(slope.dem), t["fill"])
    backend.flow.d8_pointer(t["fill"], t["direc"])
    backend.flow.d8_flow_accumulation(t["fill"], t["acc"], log=False)
    backend.delineation.extract_streams(t["acc"], t["streams"], threshold=1)

    pairs = [
        (lambda out, **k: backend.delineation.strahler_stream_order(t["direc"], t["streams"], out, **k), {"esri_pntr": False}),
        (lambda out, **k: backend.delineation.stream_link_identifier(t["direc"], t["streams"], out, **k), {"esri_pntr": False}),
        (lambda out, **k: backend.delineation.remove_short_streams(t["direc"], t["streams"], out, **k), {"esri_pntr": False}),
        (lambda out, **k: backend.flow.downslope_distance_to_stream(t["fill"], t["streams"], out, **k), {"use_dinf": False}),
    ]  # fmt: skip
    for (call, defaults), (left, spelled) in zip(
        pairs, [("a", "b"), ("c", "d"), ("e", "f"), ("g", "h")], strict=True
    ):
        call(t[left])
        call(t[spelled], **defaults)
        np.testing.assert_array_equal(_read(Path(t[left])), _read(Path(t[spelled])))
    backend.delineation.raster_streams_to_vector(t["streams"], t["direc"], str(tmp_path / "s.shp"), esri_pointer=False)  # fmt: skip
    assert not gpd.read_file(tmp_path / "s.shp").empty
    backend.delineation.extract_streams(t["acc"], str(tmp_path / "default.tif"))
    assert (tmp_path / "default.tif").exists()


@pytest.mark.parametrize("kind", ["points", "lines", "polygon"])
def test_a_vector_rasterized_with_a_zero_background_has_no_nodata_cell(slope, tmp_path: Path, kind):
    """A single point has no extent of its own, so it is rasterized on the DEM grid."""
    backend = WhiteboxWorkflowsBackend()
    rasterize = getattr(backend.raster, f"vector_{kind.replace('polygon', 'polygons')}_to_raster")
    grid = {"base": str(slope.dem), "assign_op": "last"} if kind == "points" else {"cell_size": 0.5}
    rasterize(str(getattr(slope, kind)), str(tmp_path / "out.tif"), field="id", zero_background=True, **grid)  # fmt: skip
    values = _read(tmp_path / "out.tif")
    assert np.isfinite(values).all()
    assert 1.0 in values and set(np.unique(values)) <= {0.0, 1.0}


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason="WhiteboxRasterBackend.clip sends a raster to env.clip, which takes vectors only",
)
def test_a_raster_is_clipped_to_a_polygon_by_clip(slope, tmp_path: Path):
    raster = WhiteboxWorkflowsBackend().raster
    raster.clip(str(slope.dem), str(slope.polygon), str(tmp_path / "box.tif"))
    assert np.nanmax(_read(tmp_path / "box.tif")) <= SLOPE.max()


def test_the_nodata_value_of_a_raster_is_changed_in_place(slope):
    WhiteboxWorkflowsBackend().raster.modify_no_data_value(str(slope.dem), new_value=-1.0)
    with rasterio.open(slope.dem) as src:
        assert src.nodata == -1.0
        np.testing.assert_array_equal(src.read(1), SLOPE)


@pytest.mark.allow_subprocess  # depression removal runs in a child
def test_whitebox_workflows_backend_in_memory_chain(slope, tmp_path: Path):
    backend = get_whitebox_backend()

    dem_fill = backend.flow.fill_depressions_raster(backend.raster.read_raster(str(slope.dem)))
    direc = backend.flow.d8_pointer_raster(dem_fill)
    acc = backend.flow.d8_flow_accumulation_raster(dem_fill, log=True)
    points_snap = backend.delineation.snap_pour_points_vector(
        backend.raster.read_vector(str(slope.points)), acc, 2
    )
    streams = backend.delineation.extract_streams_raster(
        backend.flow.d8_flow_accumulation_raster(dem_fill), threshold=1
    )
    on_stream = backend.delineation.jenson_snap_pour_points_vector(
        backend.raster.read_vector(str(slope.points)), streams, 2
    )
    assert backend.raster.vector_record_count(on_stream) == 1
    watershed = backend.delineation.watershed_raster(direc, points_snap)
    watershed_poly = backend.delineation.raster_to_vector_polygons_raster(watershed)
    clipped = backend.raster.clip_raster_to_polygon_raster(dem_fill, backend.raster.read_vector(str(slope.polygon)), maintain_dimensions=False)  # fmt: skip
    backend.raster.write_raster(clipped, str(tmp_path / "clipped.tif"))
    backend.raster.write_vector(watershed_poly, str(tmp_path / "watershed_mem.shp"))

    assert (tmp_path / "clipped.tif").exists()
    assert (tmp_path / "watershed_mem.shp").exists()
