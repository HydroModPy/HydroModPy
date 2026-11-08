"""The numpy engine on rasters the conformance terrains do not hold: no CRS, holes, bad pointers."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import rasterio

from hydromodpy.catchment.terrain.numpy_engine import NumpyTerrainEngine
from hydromodpy.catchment.terrain.port import ConditioningExtent, Outlet
from hydromodpy.core.exceptions import TerrainProductError
from tests._helpers.geotiffs import write_geotiff

RES = 10.0
EAST = 2
"""The ``d8_wbt`` code of the eastern neighbor."""


def _plane_east(rows: int = 5, cols: int = 6) -> np.ndarray:
    return np.tile(100.0 - np.arange(cols, dtype=float), (rows, 1))


def _chain(out, values=None, **geotiff):
    """Write *values* (a 5 x 6 plane draining east by default) and route it."""
    values = _plane_east() if values is None else values
    dem = write_geotiff(out / "dem.tif", values, cell=RES, **geotiff)
    engine = NumpyTerrainEngine()
    conditioned = engine.condition_dem(
        dem, method="fill", extent=ConditioningExtent.regional(), out=out / "fill.tif"
    )
    directions = engine.drainage_directions(conditioned, out=out / "pointer.tif")
    accumulation = engine.flow_accumulation(
        directions, units="cells", transform="none", out=out / "acc.tif"
    )
    return engine, accumulation


def _outlet(row: int, col: int, rows: int = 5) -> Outlet:
    return Outlet(outlet_id="exit", x=(col + 0.5) * RES, y=(rows - row - 0.5) * RES)


def test_a_grid_with_no_crs_and_no_nodata_routes_and_delineates(tmp_path) -> None:
    engine, accumulation = _chain(tmp_path, crs=None, dtype="float32")
    (catchment,) = engine.delineate(
        accumulation, [_outlet(2, 5)], out_dir=tmp_path / "c", snap_distance_m=RES
    )
    assert accumulation.directions.conditioned_dem.crs == ""
    assert catchment.cell_count == 6  # the row of the outlet, on a plane draining east
    assert catchment.boundary_path.is_file()


def test_a_hole_beside_the_outlet_is_neither_a_donor_nor_a_snap_target(tmp_path) -> None:
    values = _plane_east()
    values[0, 5] = -9999.0
    engine, accumulation = _chain(tmp_path, values, nodata=-9999.0, dtype="float32")
    (catchment,) = engine.delineate(
        accumulation, [_outlet(1, 5)], out_dir=tmp_path / "c", snap_distance_m=4 * RES
    )
    # Row 0 goes round the hole into the outlet, which the snap does not leave.
    assert catchment.cell_count == 2 * 6 - 1
    assert (catchment.snapped_x, catchment.snapped_y) == pytest.approx((55.0, 35.0))


def test_an_outlet_off_every_data_cell_and_a_pointer_in_another_convention_are_refused(
    tmp_path,
) -> None:
    engine, accumulation = _chain(tmp_path, nodata=-9999.0)
    foreign = replace(accumulation.directions, pointer_convention="d8_esri")
    with pytest.raises(TerrainProductError, match="found no data cell"):
        engine.delineate(
            accumulation, [_outlet(2, 50)], out_dir=tmp_path / "c", snap_distance_m=RES
        )
    with pytest.raises(TerrainProductError, match="d8_wbt"):
        engine.flow_accumulation(foreign, units="cells", transform="none", out=tmp_path / "a.tif")


def test_a_pointer_off_the_grid_or_into_a_hole_ends_the_path(tmp_path) -> None:
    """Row 0 drains into a hole, every last column drains off the grid."""
    codes = np.full((2, 3), EAST, dtype="int16")
    codes[0, 1] = -32768
    pointer = write_geotiff(tmp_path / "pointer.tif", codes, cell=RES, nodata=-32768)
    engine, accumulation = _chain(tmp_path / "chain", _plane_east(2, 3))
    counted = engine.flow_accumulation(
        replace(accumulation.directions, path=pointer),
        units="cells", transform="none", out=tmp_path / "acc.tif",
    )  # fmt: skip
    with rasterio.open(counted.path) as src:
        assert src.read(1, masked=True).filled(0).tolist() == [[1, 0, 1], [1, 2, 3]]
