"""The capped breach translates metres to the tool's units, and only for itself."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import TerrainCapabilityError, TerrainRequestError
from hydromodpy.spatial.terrain import CappedBreach, ConditioningExtent
from hydromodpy.spatial.terrain.whitebox_engine import WhiteboxTerrainEngine

rasterio = pytest.importorskip("rasterio")


class _Raster:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeRasterOps:
    def read_raster(self, path: str) -> _Raster:
        return _Raster(path)

    def write_raster(self, raster: _Raster, path: str) -> None:
        Path(path).write_bytes(Path(raster.path).read_bytes())


class _FakeFlowOps:
    """Records what the engine hands the tool, and answers the DEM unchanged."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def breach_depressions_raster(self, source: _Raster, **options: object) -> _Raster:
        self.calls.append(("breach", options))
        return source

    def fill_depressions_raster(self, source: _Raster, **options: object) -> _Raster:
        self.calls.append(("fill", options))
        return source


class _FakeBackend:
    def __init__(self) -> None:
        self.raster = _FakeRasterOps()
        self.flow = _FakeFlowOps()


def _dem(path: Path, res: float) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=6,
        width=6,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        nodata=-9999.0,
        transform=rasterio.transform.from_origin(0.0, 6 * res, res, res),
    ) as dst:
        dst.write(np.arange(36, dtype="float32").reshape(6, 6), 1)
    return path


def _condition(tmp_path: Path, res: float, method):
    backend = _FakeBackend()
    result = WhiteboxTerrainEngine(backend).condition_dem(
        _dem(tmp_path / "dem.tif", res),
        method=method,
        extent=ConditioningExtent.regional(),
        out=tmp_path / "out" / "conditioned.tif",
    )
    return backend.flow.calls, result


@pytest.mark.parametrize(
    ("res", "max_distance_m", "cells"),
    [
        (25.0, 200.0, 8),
        (5.0, 200.0, 40),
        (25.0, 210.0, 9),
        (25.0, 1.0, 1),
        (5.0, 12.0, 3),
    ],
)
def test_metres_become_cells_rounded_up_and_never_below_one(
    tmp_path, res, max_distance_m, cells
) -> None:
    calls, result = _condition(tmp_path, res, CappedBreach(0.5, max_distance_m))

    assert calls == [("breach", {"max_dist": cells, "max_cost": 0.5, "fill_deps": True})]
    assert result.breach_report.max_dist_cells == cells


def test_the_depth_in_metres_is_the_cost_in_metres(tmp_path) -> None:
    calls, result = _condition(tmp_path, 25.0, CappedBreach(max_depth_m=1.25, max_distance_m=50.0))

    assert calls[0][1]["max_cost"] == 1.25
    assert result.breach_report.max_cost_m == 1.25


def test_the_flat_increment_is_left_to_the_tool(tmp_path) -> None:
    calls, _result = _condition(tmp_path, 25.0, CappedBreach(0.5, 200.0))

    assert "flat_increment" not in calls[0][1]


def test_the_method_is_recorded_on_the_product(tmp_path) -> None:
    method = CappedBreach(0.5, 200.0)
    _calls, result = _condition(tmp_path, 25.0, method)

    assert result.method == method


def test_fill_and_breach_call_the_tool_as_they_always_did(tmp_path) -> None:
    fill_calls, fill = _condition(tmp_path, 25.0, "fill")
    breach_calls, breach = _condition(tmp_path, 25.0, "breach")

    assert fill_calls == [("fill", {})]
    assert breach_calls == [("breach", {})]
    assert fill.breach_report is None
    assert breach.breach_report is None


@pytest.mark.parametrize(
    ("depth", "distance"), [(0.0, 200.0), (-1.0, 200.0), (0.5, 0.0), (float("nan"), 200.0)]
)
def test_a_cap_that_bounds_nothing_is_refused(depth, distance) -> None:
    with pytest.raises(TerrainRequestError):
        CappedBreach(max_depth_m=depth, max_distance_m=distance)


def test_a_method_no_engine_names_is_still_refused(tmp_path) -> None:
    with pytest.raises(TerrainCapabilityError):
        _condition(tmp_path, 25.0, "carve")


class _LoweringFlowOps(_FakeFlowOps):
    """Answers a copy of the DEM with one cell cut by ``cut_m``."""

    def __init__(self, directory: Path, cut_m: float) -> None:
        super().__init__()
        self._directory = directory
        self._cut_m = cut_m

    def breach_depressions_raster(self, source: _Raster, **options: object) -> _Raster:
        super().breach_depressions_raster(source, **options)
        with rasterio.open(source.path) as src:
            profile = src.profile
            data = src.read(1)
        data[3, 3] -= self._cut_m
        lowered = self._directory / "lowered.tif"
        with rasterio.open(lowered, "w", **profile) as dst:
            dst.write(data, 1)
        return _Raster(str(lowered))


def _condition_with_cut(tmp_path: Path, cut_m: float, max_depth_m: float):
    backend = _FakeBackend()
    backend.flow = _LoweringFlowOps(tmp_path, cut_m)
    return WhiteboxTerrainEngine(backend).condition_dem(
        _dem(tmp_path / "dem.tif", 25.0),
        method=CappedBreach(max_depth_m, 200.0),
        extent=ConditioningExtent.regional(),
        out=tmp_path / "out" / "conditioned.tif",
    )


def test_a_cut_deeper_than_the_depth_cap_is_warned_about_with_both_values(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        result = _condition_with_cut(tmp_path, cut_m=0.56, max_depth_m=0.5)

    assert result.breach_report.max_lowering_m == pytest.approx(0.56, abs=1e-5)
    (warning,) = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert "0.560" in warning
    assert "0.500" in warning
    assert "cumulative" in warning


@pytest.mark.parametrize("cut_m", [0.3, 0.505])
def test_a_cut_within_the_cap_and_its_centimetre_is_not_warned_about(
    tmp_path, caplog: pytest.LogCaptureFixture, cut_m
) -> None:
    with caplog.at_level(logging.WARNING):
        _condition_with_cut(tmp_path, cut_m=cut_m, max_depth_m=0.5)

    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
