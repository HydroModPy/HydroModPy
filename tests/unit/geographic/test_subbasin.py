"""Sub-basins upstream of the gauges, the intermittency points and a declared list."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest

from hydromodpy.core.state.paths import preprocessing_dir
from hydromodpy.spatial.geographic import subbasin as subbasin_module
from hydromodpy.spatial.geographic.subbasin import Subbasin
from tests._helpers.geographic_cases import OUTLET_CATCHMENT, delineate_on_fake_backend
from tests._helpers.whitebox_double import FakeWhiteboxBackend


@pytest.fixture
def parent(tmp_path, monkeypatch):
    """A delineated catchment, and a Whitebox double that also measures polygon areas."""
    backend = FakeWhiteboxBackend()

    def polygon_area(path: str) -> None:
        frame = gpd.read_file(path)
        frame["AREA"] = frame.area
        frame.to_file(path)

    backend.raster.polygon_area = polygon_area
    monkeypatch.setattr(subbasin_module, "resolve_delineation_backend", lambda: backend)
    return delineate_on_fake_backend(tmp_path, monkeypatch, OUTLET_CATCHMENT)


def test_each_station_and_each_declared_point_gets_a_sub_basin_inside_its_parent(
    parent, tmp_path, caplog
) -> None:
    hydrometry = SimpleNamespace(
        code_bh=["J0001", ""], x_coord=[450.0, 450.0], y_coord=[450.0, 350.0]
    )
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
    assert names == [
        "hydrometry_J0001",
        "hydrometry_default_2",
        "intermittency_ONDE1",
        "subbasin_S1",
    ]
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


def test_a_runtime_without_a_preprocessing_folder_writes_under_the_output_path(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(subbasin_module, "resolve_delineation_backend", FakeWhiteboxBackend)

    sub = Subbasin(SimpleNamespace(), None, None, sub_snap_dist=50, out_path=str(tmp_path))

    assert Path(sub.subbasin_path) == preprocessing_dir(tmp_path) / "subbasin"
    assert list(Path(sub.subbasin_path).iterdir()) == []


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
