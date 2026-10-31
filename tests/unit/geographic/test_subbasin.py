"""Sub-basins upstream of the gauges, the intermittency points and a declared list."""

import logging
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio

from hydromodpy.core.exceptions import TerrainProductError
from hydromodpy.core.state.paths import preprocessing_dir
from hydromodpy.spatial.geographic import subbasin as subbasin_module
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products
from hydromodpy.spatial.geographic.subbasin import Subbasin
from tests._helpers.geographic_cases import LAMBERT, OUTLET_CATCHMENT, delineate_on_fake_backend
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.whitebox_double import FakeWhiteboxBackend

RES = 25.0
SIZE = 15


def _measuring_double() -> FakeWhiteboxBackend:
    """The Whitebox double, plus the polygon area the real backend writes as ``AREA``."""
    backend = FakeWhiteboxBackend()

    def polygon_area(path: str) -> None:
        frame = gpd.read_file(path)
        frame["AREA"] = frame.area
        frame.to_file(path)

    backend.raster.polygon_area = polygon_area
    return backend


@pytest.fixture
def parent(tmp_path, monkeypatch):
    """A delineated catchment, and a Whitebox double that also measures polygon areas."""
    backend = _measuring_double()
    monkeypatch.setattr(subbasin_module, "resolve_delineation_backend", lambda: backend)
    return delineate_on_fake_backend(tmp_path, monkeypatch, OUTLET_CATCHMENT)


def test_each_station_and_each_declared_point_gets_a_sub_basin_inside_its_parent(
    parent, tmp_path, caplog
) -> None:
    hydrometry = SimpleNamespace(code_bh=["J0001", ""], x_coord=[450.0] * 2, y_coord=[450.0, 350.0])
    point = SimpleNamespace(x=450.0, y=450.0)
    intermittency = SimpleNamespace(
        points=[
            SimpleNamespace(station_id="ONDE1", location=point),
            SimpleNamespace(station_id="unplaced", location=None),
            SimpleNamespace(location=point),  # no station id: the rest is skipped
        ]
    )
    declared = tmp_path / "declared"
    declared.mkdir()
    (declared / "points.csv").write_text("code_sub;x_outlet;y_outlet\nS1;450;450\n")
    with caplog.at_level(logging.WARNING):
        sub = Subbasin(parent, hydrometry, intermittency, sub_snap_dist=100, add_path=declared)
    names = sorted(path.name for path in Path(sub.subbasin_path).iterdir())
    expected = ["hydrometry_J0001", "hydrometry_default_2", "intermittency_ONDE1", "subbasin_S1"]
    assert names == expected
    assert "Hydrometry code missing at index 1" in caplog.text
    catchment = gpd.read_file(parent.watershed_shp).geometry.union_all()
    for name in names:
        folder = Path(sub.subbasin_path) / name
        basin = gpd.read_file(folder / "watershed.shp").geometry.union_all()
        assert basin.area > 0.0
        assert basin.difference(catchment.buffer(1.0)).is_empty, name
        assert (folder / "watershed_dem.tif").is_file()
        assert (folder / "watershed_contour.shp").is_file()
    again = Path(sub.subbasin_path) / "hydrometry_J0001"
    sub.extract_interest_zones(parent, 450.0, 450.0, str(again), 100)
    assert (again / "watershed.shp").is_file()


@pytest.mark.parametrize("out_path", ["given", None])  # None: ``output/`` of the working directory
def test_a_runtime_without_a_preprocessing_folder_writes_under_the_output_path(
    out_path, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(subbasin_module, "resolve_delineation_backend", FakeWhiteboxBackend)
    monkeypatch.chdir(tmp_path)
    root = tmp_path / (out_path or "output")
    given = {"out_path": str(root)} if out_path else {}
    sub = Subbasin(SimpleNamespace(), None, None, sub_snap_dist=50, **given)
    assert Path(sub.subbasin_path) == preprocessing_dir(root) / "subbasin"
    assert list(Path(sub.subbasin_path).iterdir()) == []
    with pytest.raises(TerrainProductError, match="_flow_products"):
        sub.extract_interest_zones(SimpleNamespace(), 1.0, 2.0, str(tmp_path / "gauge"), 50)


def _backend_for(engine_id: str, monkeypatch) -> object:
    """The double beside the numpy engine, the real backend beside the Whitebox one."""
    if engine_id == "numpy_d8":
        return _measuring_double()
    pytest.importorskip("whitebox_workflows")
    from hydromodpy.spatial.delineation import get_whitebox_backend
    from tests._helpers.whitebox import configure_whitebox_single_thread

    configure_whitebox_single_thread(monkeypatch)
    return get_whitebox_backend()


@pytest.mark.parametrize(
    "engine_id",
    # Whitebox runs its depression tools in a child process.
    ["numpy_d8", pytest.param("whitebox_workflows", marks=pytest.mark.allow_subprocess)],
)
def test_a_gauge_sub_basin_is_delineated_by_the_engine_the_run_routed_with(
    engine_id, tmp_path, monkeypatch
) -> None:
    """A V valley drains through its exit cell, so the gauge there sees the whole valley."""
    backend = _backend_for(engine_id, monkeypatch)
    monkeypatch.setattr(subbasin_module, "resolve_delineation_backend", lambda: backend)
    rows, cols = np.mgrid[0:SIZE, 0:SIZE]
    valley = 100.0 - rows * 0.5 + np.abs(cols - SIZE // 2) * 2.0
    dem = write_geotiff(tmp_path / "dem.tif", valley, cell=RES, crs=LAMBERT, nodata=-9999.0, dtype="float32")  # fmt: skip
    correcflow = tmp_path / "correcflow"
    runtime = SimpleNamespace(
        _flow_products=build_regional_flow_products(
            dem_init_path=dem,
            dem_out_dir_path=correcflow,
            dem_correc_type="fill",
            crs_project=LAMBERT,
            backend=backend,
            engine_id=engine_id,
        ),
        terrain_engine=engine_id,
        crs_proj=LAMBERT,
        correcflow_path=str(correcflow),
        watershed_buff_dem=str(dem),
        stable_folder=str(tmp_path / "stable"),
    )
    exit_x, exit_y = (SIZE // 2 + 0.5) * RES, 0.5 * RES
    gauge = SimpleNamespace(code_bh=["J0001"], x_coord=[exit_x], y_coord=[exit_y + RES])
    sub = Subbasin(runtime, gauge, None, sub_snap_dist=int(RES * 4))
    folder = Path(sub.subbasin_path) / "hydrometry_J0001"
    basin = gpd.read_file(folder / "watershed.shp")
    whole_valley = SIZE * SIZE * RES * RES
    assert basin.geometry.area.sum() == pytest.approx(whole_valley, rel=0.0, abs=1e-6)
    assert basin["AREA"].sum() == pytest.approx(whole_valley, rel=1e-9)
    snapped = gpd.read_file(folder / "outlet_snap.shp").geometry.iloc[0]
    assert (snapped.x, snapped.y) == pytest.approx((exit_x, exit_y))
    assert (folder / "watershed_contour.shp").is_file()
    with rasterio.open(folder / "watershed_dem.tif") as src:
        assert int(src.read(1, masked=True).count()) == SIZE * SIZE


@pytest.mark.xfail(
    strict=True,
    reason="Subbasin swallows the failure of a station at debug level (subbasin.py:96), "
    "so a gauge without its sub-basin leaves no warning.",
)
def test_a_station_that_cannot_be_delineated_is_reported(parent, caplog, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("no accumulation here")

    monkeypatch.setattr(Subbasin, "extract_interest_zones", fail)
    hydrometry = SimpleNamespace(code_bh=["J0001"], x_coord=[450.0], y_coord=[450.0])
    with caplog.at_level(logging.WARNING):
        Subbasin(parent, hydrometry, None, sub_snap_dist=100)
    assert "J0001" in caplog.text
