"""The capped breach translates metres to the tool's units, and only for itself."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import TerrainCapabilityError, TerrainRequestError
from hydromodpy.spatial.terrain import CappedBreach, ConditioningExtent
from hydromodpy.spatial.terrain.whitebox_engine import WhiteboxTerrainEngine
from tests._helpers.geotiffs import write_geotiff


def _surface() -> np.ndarray:
    return np.arange(36.0).reshape(6, 6)


def _write(path: Path, values: np.ndarray, res: float = 25.0) -> SimpleNamespace:
    path = write_geotiff(path, values, cell=res, nodata=-9999.0, dtype="float32")
    return SimpleNamespace(path=str(path))


class _FakeFlowOps:
    """Records what the engine hands the tool; a breach lowers cell (3, 3) by ``cut_m``."""

    def __init__(self, directory: Path, cut_m: float) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._directory = directory
        self._cut_m = cut_m

    def breach_depressions_raster(self, source, **options: object):
        self.calls.append(("breach", options))
        if not self._cut_m:
            return source
        values = _surface()
        values[3, 3] -= self._cut_m
        return _write(self._directory / "lowered.tif", values)

    def fill_depressions_raster(self, source, **options: object):
        self.calls.append(("fill", options))
        return source


def _condition(tmp_path: Path, res: float, method, cut_m: float = 0.0):
    flow = _FakeFlowOps(tmp_path, cut_m)
    raster = SimpleNamespace(
        read_raster=lambda path: SimpleNamespace(path=path),
        write_raster=lambda raster, path: shutil.copyfile(raster.path, path),
    )
    result = WhiteboxTerrainEngine(SimpleNamespace(raster=raster, flow=flow)).condition_dem(
        _write(tmp_path / "dem.tif", _surface(), res).path,
        method=method,
        extent=ConditioningExtent.regional(),
        out=tmp_path / "out" / "conditioned.tif",
    )
    return flow.calls, result


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


def test_the_depth_in_metres_is_the_cost_and_the_method_is_recorded(tmp_path) -> None:
    """The flat increment is left to the tool."""
    method = CappedBreach(max_depth_m=1.25, max_distance_m=50.0)
    calls, result = _condition(tmp_path, 25.0, method)

    assert calls[0][1]["max_cost"] == 1.25
    assert "flat_increment" not in calls[0][1]
    assert result.breach_report.max_cost_m == 1.25
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


def test_a_cut_deeper_than_the_depth_cap_is_warned_about_with_both_values(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        _calls, result = _condition(tmp_path, 25.0, CappedBreach(0.5, 200.0), cut_m=0.56)

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
        _condition(tmp_path, 25.0, CappedBreach(0.5, 200.0), cut_m=cut_m)

    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
