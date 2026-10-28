"""The numpy engine on rasters the conformance terrains do not hold: no CRS, holes, bad pointers."""

from __future__ import annotations

import numpy as np
import pytest
import rasterio

from hydromodpy.core.exceptions import TerrainProductError
from hydromodpy.spatial.terrain.numpy_engine import NumpyTerrainEngine
from hydromodpy.spatial.terrain.port import ConditioningExtent, DrainageDirections, Outlet
from tests._helpers.geotiffs import write_geotiff

RES = 10.0
EAST = 2
"""The ``d8_wbt`` code of the eastern neighbour."""


def _plane_east(rows: int = 5, cols: int = 6) -> np.ndarray:
    return np.tile(100.0 - np.arange(cols, dtype=float), (rows, 1))


def _chain(dem, out):
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
    dem = write_geotiff(tmp_path / "dem.tif", _plane_east(), cell=RES, crs=None, dtype="float32")
    engine, accumulation = _chain(dem, tmp_path)

    (catchment,) = engine.delineate(
        accumulation, [_outlet(2, 5)], out_dir=tmp_path / "c", snap_distance_m=RES
    )

    assert accumulation.directions.conditioned_dem.crs == ""
    assert catchment.cell_count == 6  # the row of the outlet, on a plane draining east
    assert catchment.boundary_path.is_file()


def test_a_hole_beside_the_outlet_is_neither_a_donor_nor_a_snap_target(tmp_path) -> None:
    values = _plane_east()
    values[0, 5] = -9999.0
    dem = write_geotiff(tmp_path / "dem.tif", values, cell=RES, nodata=-9999.0, dtype="float32")
    engine, accumulation = _chain(dem, tmp_path)

    (catchment,) = engine.delineate(
        accumulation, [_outlet(1, 5)], out_dir=tmp_path / "c", snap_distance_m=4 * RES
    )

    # Row 0 goes round the hole into the outlet, which the snap does not leave.
    assert catchment.cell_count == 2 * 6 - 1
    assert (catchment.snapped_x, catchment.snapped_y) == pytest.approx(
        ((5 + 0.5) * RES, (5 - 1 - 0.5) * RES)
    )


def test_an_outlet_whose_window_holds_no_data_cell_is_refused(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", _plane_east(), cell=RES, nodata=-9999.0)
    engine, accumulation = _chain(dem, tmp_path)

    with pytest.raises(TerrainProductError, match="found no data cell"):
        engine.delineate(
            accumulation, [_outlet(2, 50)], out_dir=tmp_path / "c", snap_distance_m=RES
        )


def test_a_pointer_off_the_grid_or_into_a_hole_ends_the_path(tmp_path) -> None:
    """Row 0 drains into a hole, every last column drains off the grid."""
    codes = np.full((2, 3), EAST, dtype="int16")
    codes[0, 1] = -32768
    pointer = write_geotiff(tmp_path / "pointer.tif", codes, cell=RES, nodata=-32768)
    dem = write_geotiff(tmp_path / "dem.tif", _plane_east(2, 3), cell=RES)
    engine, accumulation = _chain(dem, tmp_path / "chain")
    directions = DrainageDirections(
        path=pointer,
        pointer_convention="d8_wbt",
        conditioned_dem=accumulation.directions.conditioned_dem,
    )

    counted = engine.flow_accumulation(
        directions, units="cells", transform="none", out=tmp_path / "acc.tif"
    )

    with rasterio.open(counted.path) as src:
        values = src.read(1, masked=True)
    assert values.filled(0).tolist() == [[1, 0, 1], [1, 2, 3]]


def test_a_pointer_in_another_convention_is_refused(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", _plane_east(), cell=RES)
    engine, accumulation = _chain(dem, tmp_path)
    foreign = DrainageDirections(
        path=accumulation.directions.path,
        pointer_convention="d8_esri",
        conditioned_dem=accumulation.directions.conditioned_dem,
    )

    with pytest.raises(TerrainProductError, match="d8_wbt"):
        engine.flow_accumulation(foreign, units="cells", transform="none", out=tmp_path / "a.tif")
