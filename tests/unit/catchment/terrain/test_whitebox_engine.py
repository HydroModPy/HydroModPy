"""The Whitebox engine conditions a DEM, and translates a capped breach from m to the tool's units.

A fake flow tool records what the engine hands it. A breach lowers cell (3, 3) of a
6 x 6 surface of 25 m cells by a chosen cut (m).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.terrain.port import CappedBreach, ConditioningExtent
from hydromodpy.catchment.terrain.whitebox_engine import WhiteboxTerrainEngine
from hydromodpy.core.exceptions import TerrainCapabilityError, TerrainRequestError
from tests._helpers.geotiffs import write_geotiff


def surface():
    return np.arange(36.0).reshape(6, 6)


def write_surface(path: Path, values: np.ndarray, cell_m: float = 25.0) -> SimpleNamespace:
    path = write_geotiff(path, values, cell=cell_m, nodata=-9999.0, dtype="float32")
    return SimpleNamespace(path=str(path))


class FakeFlowOps:
    """Records the calls of the engine. A breach lowers cell (3, 3) by ``cut_m``."""

    def __init__(self, directory: Path, cut_m: float) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._directory = directory
        self._cut_m = cut_m

    def breach_depressions_raster(self, source, **options: object):
        self.calls.append(("breach", options))
        if not self._cut_m:
            return source
        values = surface()
        values[3, 3] -= self._cut_m
        return write_surface(self._directory / "lowered.tif", values)

    def fill_depressions_raster(self, source, **options: object):
        self.calls.append(("fill", options))
        return source

    def d8_pointer_raster(self, source, **options: object):
        return source


def engine_with_fake_tool(tmp_path: Path, cut_m: float = 0.0):
    flow = FakeFlowOps(tmp_path, cut_m)
    raster = SimpleNamespace(
        read_raster=lambda path: SimpleNamespace(path=path),
        write_raster=lambda raster, path: shutil.copyfile(raster.path, path),
    )
    return flow, WhiteboxTerrainEngine(SimpleNamespace(raster=raster, flow=flow))


def condition(tmp_path: Path, engine: WhiteboxTerrainEngine, method):
    return engine.condition_dem(
        write_surface(tmp_path / "dem.tif", surface()).path,
        method=method,
        extent=ConditioningExtent.regional(),
        out=tmp_path / "out" / "conditioned.tif",
    )


def test_capped_breach_cost_in_metres(tmp_path):
    # The flat increment is left to the tool.
    method = CappedBreach(max_depth_m=1.25, max_distance_m=50.0)
    flow, engine = engine_with_fake_tool(tmp_path)

    result = condition(tmp_path, engine, method)

    assert flow.calls[0][1]["max_cost"] == 1.25
    assert "flat_increment" not in flow.calls[0][1]
    assert result.breach_report.max_cost_m == 1.25
    assert result.method == method


@pytest.mark.parametrize("method", ["fill", "breach"])
def test_plain_methods_call_tool_bare(tmp_path, method):
    flow, engine = engine_with_fake_tool(tmp_path)

    result = condition(tmp_path, engine, method)

    assert flow.calls == [(method, {})]
    assert result.breach_report is None


# "provided" names a DEM nobody conditions here, so the refusal says how to build it.
METHOD_REFUSALS = [
    pytest.param("carve", TerrainCapabilityError, "carve", id="unknown method"),
    pytest.param("provided", TerrainRequestError, r"ConditionedDem\.provided", id="provided"),
]


@pytest.mark.parametrize(("method", "error", "match"), METHOD_REFUSALS)
def test_method_refusals(tmp_path, method, error, match):
    flow, engine = engine_with_fake_tool(tmp_path)

    with pytest.raises(error, match=match):
        condition(tmp_path, engine, method)

    assert flow.calls == []


CAP_REFUSALS = [
    pytest.param(0.0, 200.0, id="no depth"),
    pytest.param(-1.0, 200.0, id="negative depth"),
    pytest.param(0.5, 0.0, id="no distance"),
    pytest.param(float("nan"), 200.0, id="nan depth"),
]


@pytest.mark.parametrize(("depth", "distance"), CAP_REFUSALS)
def test_cap_refusals(depth, distance):
    with pytest.raises(TerrainRequestError):
        CappedBreach(max_depth_m=depth, max_distance_m=distance)


# Depth cap is 0.5 m, and a cut is tolerated up to the next centimetre.
@pytest.mark.parametrize("cut_m", [0.3, 0.505], ids=["under the cap", "within the centimetre"])
def test_cut_within_cap_is_silent(tmp_path, caplog, cut_m):
    _, engine = engine_with_fake_tool(tmp_path, cut_m)

    with caplog.at_level(logging.WARNING):
        condition(tmp_path, engine, CappedBreach(0.5, 200.0))

    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_cut_past_cap_warns(tmp_path, caplog):
    _, engine = engine_with_fake_tool(tmp_path, 0.56)

    with caplog.at_level(logging.WARNING):
        result = condition(tmp_path, engine, CappedBreach(0.5, 200.0))

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert result.breach_report.max_lowering_m == pytest.approx(0.56, abs=1e-5)
    (warning,) = warnings
    assert "0.560" in warning
    assert "0.500" in warning
    assert "cumulative" in warning
