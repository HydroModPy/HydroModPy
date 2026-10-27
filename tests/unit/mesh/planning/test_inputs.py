"""The planner inputs are plain frozen data on the DEM grid, in its CRS."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import MeshRequestError
from tests._helpers.mesh_cases import LAMBERT93_WKT, planning_inputs


def test_inputs_in_another_crs_than_the_dem_grid_are_refused() -> None:
    with pytest.raises(
        MeshRequestError, match="the planning inputs and the DEM grid name different CRS"
    ):
        planning_inputs(crs_wkt=LAMBERT93_WKT)


def test_the_sequences_of_the_inputs_are_kept_as_tuples() -> None:
    """A list handed by the mesh step cannot change after the request was hashed."""
    lake = box(100.0, 100.0, 200.0, 200.0)
    wall = LineString([(0.0, 0.0), (1.0, 1.0)])

    inputs = planning_inputs(lakes=[lake], barriers=[wall], notes=["a note"], refinement_zones=[])

    assert (inputs.lakes, inputs.barriers, inputs.notes) == ((lake,), (wall,), ("a note",))
    assert inputs.refinement_zones == () and inputs.lake_structures == ()
