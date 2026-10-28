"""The planner inputs are plain frozen data on the DEM grid, in its CRS."""

from __future__ import annotations

from shapely.geometry import LineString, box

from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec, planning_inputs


def test_the_inputs_are_in_the_crs_of_the_dem_grid() -> None:
    inputs = planning_inputs(grid_spec(4, 4, 10.0, crs_wkt=LAMBERT93_WKT))

    assert inputs.crs_wkt == inputs.dem_grid.crs_wkt == LAMBERT93_WKT


def test_the_sequences_of_the_inputs_are_kept_as_tuples() -> None:
    """A list handed by the mesh step cannot change after the request was hashed."""
    lake = box(100.0, 100.0, 200.0, 200.0)
    wall = LineString([(0.0, 0.0), (1.0, 1.0)])

    inputs = planning_inputs(lakes=[lake], barriers=[wall], notes=["a note"], refinement_zones=[])

    assert (inputs.lakes, inputs.barriers, inputs.notes) == ((lake,), (wall,), ("a note",))
    assert inputs.refinement_zones == () and inputs.lake_structures == ()
