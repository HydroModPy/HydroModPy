"""Without a stream network each lake is fed the runoff of the ground it drains.

The area comes from the D8 pointer of the regional flow products: a cell belongs
to the first lake its path meets. Two lakes then share the basin runoff once, and
each one is fed in proportion to its own area.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.structure_binders import apply_lake_meteo_forcings_to_flow
from hydromodpy.spatial.geographic.core.lake_catchments import lake_contributing_areas_m2
from hydromodpy.workflow.steps.data import lake_runoff_areas

_CELL_M = 10.0
_ROWS, _COLS = 6, 10
_EAST = 2  # D8 code of the eastern neighbour


def _write_pointer(path: Path, *, code: int = _EAST) -> Path:
    """A 6 x 10 grid of 10 m cells, every cell draining to its eastern neighbour."""
    pointer = np.full((_ROWS, _COLS), code, dtype="int16")
    transform = from_origin(0.0, _ROWS * _CELL_M, _CELL_M, _CELL_M)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=_ROWS,
        width=_COLS,
        count=1,
        dtype="int16",
        transform=transform,
        crs="EPSG:2154",
    ) as dst:
        dst.write(pointer, 1)
    return path


def _column(first: int, last: int) -> object:
    """Footprint of the columns first..last (inclusive), over every row."""
    return box(first * _CELL_M, 0.0, (last + 1) * _CELL_M, _ROWS * _CELL_M)


def test_each_lake_takes_the_ground_that_drains_to_it_first(tmp_path: Path) -> None:
    pointer = _write_pointer(tmp_path / "d8.tif")

    areas = lake_contributing_areas_m2(
        d8_pointer_tif=str(pointer),
        lake_polygons={"upper": _column(3, 3), "lower": _column(7, 7)},
    )

    # Columns 0-3 end in the upper lake, 4-7 in the lower one, 8-9 in neither.
    cell = _CELL_M**2
    assert areas["upper"] == pytest.approx(4 * _ROWS * cell)
    assert areas["lower"] == pytest.approx(4 * _ROWS * cell)


def test_a_lake_on_the_basin_edge_closes_the_basin_with_the_other(tmp_path: Path) -> None:
    pointer = _write_pointer(tmp_path / "d8.tif")

    areas = lake_contributing_areas_m2(
        d8_pointer_tif=str(pointer),
        lake_polygons={"upper": _column(3, 3), "lower": _column(9, 9)},
    )

    assert sum(areas.values()) == pytest.approx(_ROWS * _COLS * _CELL_M**2)


def test_the_count_stays_inside_the_watershed(tmp_path: Path) -> None:
    pointer = _write_pointer(tmp_path / "d8.tif")
    first_two_rows = box(0.0, (_ROWS - 2) * _CELL_M, _COLS * _CELL_M, _ROWS * _CELL_M)

    areas = lake_contributing_areas_m2(
        d8_pointer_tif=str(pointer),
        lake_polygons={"upper": _column(3, 3)},
        watershed_polygons=[first_two_rows],
    )

    assert areas["upper"] == pytest.approx(2 * 4 * _CELL_M**2)


def test_a_lake_at_the_head_of_the_grid_drains_only_its_own_column(tmp_path: Path) -> None:
    pointer = _write_pointer(tmp_path / "d8.tif")

    areas = lake_contributing_areas_m2(
        d8_pointer_tif=str(pointer),
        lake_polygons={"head": _column(0, 0), "mid": _column(5, 5)},
    )

    assert areas["head"] == pytest.approx(_ROWS * _CELL_M**2)
    assert areas["mid"] == pytest.approx(5 * _ROWS * _CELL_M**2)


def test_a_footprint_smaller_than_a_cell_still_catches_its_cell(tmp_path: Path) -> None:
    pointer = _write_pointer(tmp_path / "d8.tif")
    pond = box(41.0, 21.0, 44.0, 24.0)  # 3 m x 3 m, centre inside no cell centre

    areas = lake_contributing_areas_m2(d8_pointer_tif=str(pointer), lake_polygons={"pond": pond})

    assert areas["pond"] > 0.0


# --- the data step hands those areas to the lake runoff binder -----------------

_DATES = ["2000-01-01", "2000-01-02", "2000-01-03"]


def _window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2000-01-03"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _runoff_mm_per_day(value: float) -> LoadResult:
    record = PointRecord(
        station_id="grid_mean",
        variable="climatic",
        source="custom",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": pd.to_datetime(_DATES), "value": [value] * 3}),
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2000, 1, 3),
    )
    return LoadResult(points=[record])


def _setup_state(pointer: Path, *, lakes: dict, sfr: bool = False) -> SimpleNamespace:
    sinks_sources: dict = {"lakes": lakes}
    if sfr:
        sinks_sources["sfr"] = {"net": {}}
    flow = SimpleNamespace(sinks_sources=sinks_sources, active_bc=["lake", "sfr"] if sfr else [])
    geographic = SimpleNamespace(
        _flow_products=SimpleNamespace(direc=str(pointer)), watershed_shp=None
    )
    return SimpleNamespace(flow=flow, geographic=geographic)


def test_two_lakes_without_sfr_are_fed_the_basin_runoff_once_by_their_own_area(
    tmp_path: Path,
) -> None:
    pointer = _write_pointer(tmp_path / "d8.tif")
    lakes = {
        "upper": {"polygon": _column(3, 3)},
        "lower": {"polygon": _column(9, 9)},
    }
    state = _setup_state(pointer, lakes=lakes)
    basin_m2 = _ROWS * _COLS * _CELL_M**2

    areas = lake_runoff_areas(state)
    apply_lake_meteo_forcings_to_flow(
        flow=state.flow,
        runoff=_runoff_mm_per_day(1.0),
        simulation_window=_window(),
        catchment_area_m2=basin_m2,
        lake_contributing_areas_m2=areas,
    )

    rate = 1.0e-3 / 86400.0
    fed = state.flow.sinks_sources["lakes"]
    assert fed["upper"]["runoff"]["values"][0] == pytest.approx(rate * 4 * _ROWS * _CELL_M**2)
    assert fed["lower"]["runoff"]["values"][0] == pytest.approx(rate * 6 * _ROWS * _CELL_M**2)
    total = fed["upper"]["runoff"]["values"][0] + fed["lower"]["runoff"]["values"][0]
    assert total == pytest.approx(rate * basin_m2)


def test_a_routed_network_or_a_lone_lake_keeps_the_binder_default(tmp_path: Path) -> None:
    pointer = _write_pointer(tmp_path / "d8.tif")
    two = {"a": {"polygon": _column(2, 2)}, "b": {"polygon": _column(6, 6)}}

    assert lake_runoff_areas(_setup_state(pointer, lakes=two, sfr=True)) is None
    assert lake_runoff_areas(_setup_state(pointer, lakes={"a": two["a"]})) is None


def test_lakes_without_a_footprint_fall_back_to_the_even_split(tmp_path: Path) -> None:
    pointer = _write_pointer(tmp_path / "d8.tif")
    lakes = {"a": {"polygon": _column(2, 2)}, "b": {}}

    assert lake_runoff_areas(_setup_state(pointer, lakes=lakes)) is None
