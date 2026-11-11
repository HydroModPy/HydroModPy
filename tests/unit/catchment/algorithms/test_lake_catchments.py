"""Without a stream network each lake is fed the runoff of the ground it drains.

A cell belongs to the first lake its D8 path meets, so two lakes share the
basin runoff once, each in proportion to its own area.
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from hydromodpy.catchment.algorithms.lake_catchments import lake_contributing_areas_m2
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.boundaries.lakes import apply_lake_meteo_forcings_to_flow
from hydromodpy.workflow.steps.data import lake_runoff_areas
from tests._helpers.geotiffs import write_geotiff

_CELL_M = 10.0
_ROWS, _COLS = 6, 10
_EAST = 2  # D8 code of the eastern neighbor


def _write_pointer(path: Path, *, code: int = _EAST) -> Path:
    """A 6 x 10 grid of 10 m cells, every cell draining to its eastern neighbor."""
    return write_geotiff(path, np.full((_ROWS, _COLS), code, dtype="int16"), cell=_CELL_M)


def _column(first: int, last: int) -> object:
    """Footprint of the columns first..last (inclusive), over every row."""
    return box(first * _CELL_M, 0.0, (last + 1) * _CELL_M, _ROWS * _CELL_M)


@pytest.mark.parametrize(
    ("lakes", "expected_columns"),
    [
        # Columns 0-3 end in the upper lake, 4-7 in the lower one, 8-9 in neither.
        ({"upper": (3, 3), "lower": (7, 7)}, {"upper": 4, "lower": 4}),
        # A lake on the basin edge closes the basin with the other.
        ({"upper": (3, 3), "lower": (9, 9)}, {"upper": 4, "lower": 6}),
        # A lake at the head of the grid drains only its own column.
        ({"head": (0, 0), "mid": (5, 5)}, {"head": 1, "mid": 5}),
    ],
    ids=["two lakes", "lake on the edge", "lake at the head"],
)
def test_each_lake_takes_the_ground_that_drains_to_it_first(
    tmp_path: Path, lakes, expected_columns
) -> None:
    areas = lake_contributing_areas_m2(
        d8_pointer_tif=str(_write_pointer(tmp_path / "d8.tif")),
        lake_polygons={name: _column(*columns) for name, columns in lakes.items()},
    )
    column = _ROWS * _CELL_M**2
    assert areas == {name: pytest.approx(n * column) for name, n in expected_columns.items()}
    assert sum(areas.values()) <= _ROWS * _COLS * _CELL_M**2


def test_the_count_stays_inside_the_watershed_and_a_pond_smaller_than_a_cell_catches_it(tmp_path):
    pointer = str(_write_pointer(tmp_path / "d8.tif"))
    first_two_rows = box(0.0, (_ROWS - 2) * _CELL_M, _COLS * _CELL_M, _ROWS * _CELL_M)
    pond = box(41.0, 21.0, 44.0, 24.0)  # 3 m x 3 m, center inside no cell center
    areas = lake_contributing_areas_m2(
        d8_pointer_tif=pointer,
        lake_polygons={"upper": _column(3, 3)},
        watershed_polygons=[first_two_rows],
    )
    ponds = lake_contributing_areas_m2(d8_pointer_tif=pointer, lake_polygons={"pond": pond})
    assert areas["upper"] == pytest.approx(2 * 4 * _CELL_M**2)
    assert ponds["pond"] > 0.0
    assert lake_contributing_areas_m2(d8_pointer_tif=pointer, lake_polygons={}) == {}


def _setup_state(pointer: Path, *, lakes: dict, sfr: bool = False) -> SimpleNamespace:
    sinks_sources: dict = {"lakes": lakes}
    if sfr:
        sinks_sources["sfr"] = {"net": {}}
    flow = SimpleNamespace(sinks_sources=sinks_sources, active_bc=["lake", "sfr"] if sfr else [])
    flow_products = SimpleNamespace(direc=str(pointer))
    geographic = SimpleNamespace(_flow_products=flow_products, watershed_shp=None)
    return SimpleNamespace(flow=flow, geographic=geographic)


def test_two_lakes_without_sfr_are_fed_the_basin_runoff_once_by_their_own_area(tmp_path) -> None:
    lakes = {"upper": {"polygon": _column(3, 3)}, "lower": {"polygon": _column(9, 9)}}
    state = _setup_state(_write_pointer(tmp_path / "d8.tif"), lakes=lakes)
    basin_m2 = _ROWS * _COLS * _CELL_M**2
    days = pd.DataFrame({"datetime": pd.date_range("2000-01-01", periods=3), "value": [1.0] * 3})
    runoff = PointRecord(
        station_id="grid_mean",
        variable="climatic",
        source="file",
        unit="mm/day",
        frequency="D",
        data=days,
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2000, 1, 3),
    )
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2000-01-03"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )
    areas = lake_runoff_areas(state)
    apply_lake_meteo_forcings_to_flow(
        flow=state.flow,
        runoff=LoadResult(points=[runoff]),
        simulation_window=window,
        catchment_area_m2=basin_m2,
        lake_contributing_areas_m2=areas,
    )
    rate = 1.0e-3 / 86400.0
    fed = state.flow.sinks_sources["lakes"]
    assert fed["upper"]["runoff"]["values"][0] == pytest.approx(rate * 4 * _ROWS * _CELL_M**2)
    assert fed["lower"]["runoff"]["values"][0] == pytest.approx(rate * 6 * _ROWS * _CELL_M**2)
    total = fed["upper"]["runoff"]["values"][0] + fed["lower"]["runoff"]["values"][0]
    assert total == pytest.approx(rate * basin_m2)


def test_a_routed_network_a_lone_lake_or_a_lake_without_footprint_keeps_the_default(tmp_path):
    pointer = _write_pointer(tmp_path / "d8.tif")
    two = {"a": {"polygon": _column(2, 2)}, "b": {"polygon": _column(6, 6)}}
    assert lake_runoff_areas(_setup_state(pointer, lakes=two, sfr=True)) is None
    assert lake_runoff_areas(_setup_state(pointer, lakes={"a": two["a"]})) is None
    # Lakes without a footprint fall back to the even split.
    assert lake_runoff_areas(_setup_state(pointer, lakes={"a": two["a"], "b": {}})) is None
