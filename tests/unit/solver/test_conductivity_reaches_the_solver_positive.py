"""A zero or missing conductivity is refused, and so is a storage a transient period reads.

Sy counts on a convertible cell, Ss on a confined one, both on active cells only.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.solver.field_property_mapping import (
    require_positive_conductivity,
    require_positive_storage,
)
from hydromodpy.solver.modflow6 import build as mf6_build
from hydromodpy.solver.modflow6.builders import apply_lake_idomain_mask
from hydromodpy.spatial.field.field_param import FieldParam
from hydromodpy.spatial.field.field_spatial import WeightedAverageFieldDiscretization
from hydromodpy.spatial.field.mesh_cells import cell_values
from hydromodpy.spatial.field.unit_square_mesh import FieldMeshSquare
from tests._helpers.mf6_toy_models import regular_solver_mesh


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
            "granite": np.asarray(cell_values(mesh, granite)),
            "schist": np.asarray(cell_values(mesh, schist)),
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


@pytest.mark.parametrize(
    ("sy", "ss", "iconvert", "steady", "match"),
    [([[0.1, 0.0, 0.0], [0.1, 0.1, 0.0]], None, 1, [True, False],
      r"Sy .* 3 of 6 active convertible .*\(layer 1: 2, layer 2: 1; 3 zero, 0 not finite\)"),
     ([0.1, np.nan, 0.1], None, 1, [False], r"Sy .* 1 of 3 .*1 not finite"),
     ([[0.1] * 3] * 2, [[1e-5] * 3, [1e-5, 0.0, 1e-5]], [1, 0], [False],
      r"Ss .* 1 of 3 active confined .*\(layer 2: 1; 1 zero"),
     ([[0.1] * 3] * 2, [[0.0] * 3] * 2, 1, [False], None),
     ([[0.0] * 3] * 2, [[0.0] * 3] * 2, 1, [True, True], None)],
    ids=["sy-zero-convertible", "sy-not-finite", "ss-zero-confined", "ss-zero-convertible",
         "every-period-steady"],
)  # fmt: skip
def test_a_storage_is_refused_only_where_a_transient_period_reads_it(
    sy, ss, iconvert, steady, match
):
    sy, ss = np.asarray(sy, dtype=float), None if ss is None else np.asarray(ss, dtype=float)
    with pytest.raises(DataContractViolation, match=match) if match else nullcontext():
        require_positive_storage(
            sy, ss, active_mask=np.ones(sy.shape, bool), iconvert=iconvert, steady=steady
        )


@pytest.mark.parametrize(("dry_cell", "match"), [(0, None), (1, r"Sy .* 1 of 11 active")])
def test_modflow6_reads_the_storage_on_the_grid_the_lake_leaves(monkeypatch, dry_cell, match):
    """Sy = 0 under the lake footprint is never read; on an active cell it is refused."""
    mesh = regular_solver_mesh(2, 3)
    mesh = replace(mesh, botm=np.vstack([mesh.botm, mesh.botm - 9.0]), idomain=np.ones((2, 6)))
    mesh = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lake": [0]})
    sy = np.full((2, 6), 0.1)
    sy[0, dry_cell] = 0.0
    model = SimpleNamespace(steady=[False], nper=1, nlay=2, sy=sy, ss=sy / 1e4, flow=None, gwf=None)
    monkeypatch.setattr(mf6_build.flopy.mf6, "ModflowGwfsto", lambda gwf, **kwargs: kwargs)
    with pytest.raises(DataContractViolation, match=match) if match else nullcontext():
        mf6_build._build_storage_package(model, mesh)
