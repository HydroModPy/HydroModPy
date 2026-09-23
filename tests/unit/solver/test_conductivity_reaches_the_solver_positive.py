"""A zero or missing conductivity is refused before any solver sees it."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.solver.field_property_mapping import require_positive_conductivity
from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)


def _heterogeneous_k() -> FieldParam:
    return FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 1e-5, "schist": 1e-6},
        field_spatial_id="field_geology",
    )


def _k_with_an_uncovered_cell() -> tuple[FieldParam, np.ndarray]:
    """One cell that no zone of the support covers, as outside a clipped geology map."""
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="structured")
    n = int(mesh.n_cells)
    granite = np.zeros(n)
    schist = np.zeros(n)
    granite[: n // 2] = 1.0
    schist[n // 2 : n - 1] = 1.0
    discretization = WeightedAverageFieldDiscretization(
        mesh=mesh,
        field_id="field_geology",
        zone_keys=("granite", "schist"),
        fractions_by_zone={
            "granite": np.asarray(mesh.to_cell_values(granite)),
            "schist": np.asarray(mesh.to_cell_values(schist)),
        },
    )
    param = _heterogeneous_k()
    values = np.asarray(param.to_mesh_field(discretization).cell_values, dtype=float)
    return param, values.reshape(1, -1)


def test_an_uncovered_active_cell_is_refused_and_names_the_support():
    param, hk = _k_with_an_uncovered_cell()
    assert np.count_nonzero(hk == 0.0) == 1
    flow = SimpleNamespace(parameters={"K": param})
    with pytest.raises(DataContractViolation, match=r"1 of 9 active.*'field_geology'"):
        require_positive_conductivity(hk, active_mask=np.ones_like(hk, dtype=bool), flow=flow)


def test_an_uncovered_inactive_cell_is_accepted():
    param, hk = _k_with_an_uncovered_cell()
    active = hk > 0.0
    require_positive_conductivity(hk, active_mask=active, flow=SimpleNamespace(parameters={}))


def test_a_non_finite_conductivity_is_refused():
    hk = np.array([[1e-5, np.nan, 1e-5]])
    with pytest.raises(DataContractViolation, match=r"1 not finite"):
        require_positive_conductivity(hk, active_mask=np.array([True, True, True]))
