"""A vector geology map reaches the solver K as exact zone areas, :mod:`hydromodpy.solver.modflow_common.property_mapping`.

The MODFLOW mapping reads the polygons a vector geology keeps: a cell the
contact crosses takes the area-weighted mean of the two zone values, where the
encoded raster would give the zone of its pixel centres.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow_common.property_mapping import resolve_flow_property_arrays
from hydromodpy.spatial.field.core.field_param import FieldParam
from tests._helpers.field_cases import vector_geology_field
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def test_a_cell_the_contact_crosses_takes_the_area_mean_of_the_two_values(tmp_path: Path) -> None:
    field = vector_geology_field(tmp_path)
    # Columns of 300 m from x = 351 050: the last one, [351 950, 352 250], is 1/6 A.
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=4,
        top=np.full((2, 4), 10.0),
        botm=np.full((1, 2, 4), 0.0),
        dx=300.0,
        dy=300.0,
        xoff=351_050.0,
        yoff=6_781_000.0,
    )
    k_a, k_b = 1.0e-4, 1.0e-6
    k = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"A": k_a, "B": k_b},
        field_spatial_id="geology",
    )

    out = resolve_flow_property_arrays(
        flow=SimpleNamespace(parameters={"K": k}),
        domain=SimpleNamespace(zones={"geology": field}),
        solver_mesh=solver_mesh,
        required_properties={"K"},
    )

    mixed = (50.0 * k_a + 250.0 * k_b) / 300.0
    expected = np.tile([k_a, k_a, k_a, mixed], 2)
    np.testing.assert_allclose(out["hk_value"], expected, rtol=1e-9)
    np.testing.assert_allclose(out["hk"], expected[None, :], rtol=1e-9)
