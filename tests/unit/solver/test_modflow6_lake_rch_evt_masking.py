"""Aquifer RCH/EVT must be zeroed on lake cells to avoid double counting.

The lake's own rainfall and open-water evaporation enter through LAK, so applying
RCHA or aquifer EVT on the same cells would count those fluxes twice. The recharge
masking zeros exactly the lake cells; the EVT builder skips them entirely.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.builders import (
    build_evt_stress_period_data,
    mask_recharge_on_lake_cells,
)
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


def test_mask_recharge_zeros_only_lake_cells() -> None:
    spd = {0: np.full(6, 1.0e-8), 1: np.full(6, 2.0e-8)}
    masked = mask_recharge_on_lake_cells(spd, lake_cell_ids=[1, 4])

    for kper, expected_nonzero in ((0, 1.0e-8), (1, 2.0e-8)):
        arr = masked[kper]
        assert arr[1] == 0.0
        assert arr[4] == 0.0
        # Non-lake cells keep their recharge.
        assert arr[0] == expected_nonzero
        assert arr[[2, 3, 5]].tolist() == [expected_nonzero] * 3


def test_mask_recharge_no_lake_is_a_noop() -> None:
    spd = {0: np.full(4, 3.0e-8)}
    masked = mask_recharge_on_lake_cells(spd, lake_cell_ids=[])
    assert np.all(masked[0] == 3.0e-8)


def _evt_model() -> tuple[SimpleNamespace, SolverMesh]:
    nrow, ncol = 2, 3
    top = np.full((nrow, ncol), 10.0)
    botm = np.stack([np.full((nrow, ncol), 5.0), np.full((nrow, ncol), 0.0)])
    mesh = SolverMesh.from_structured_arrays(nrow=nrow, ncol=ncol, top=top, botm=botm)
    return SimpleNamespace(
        ncpl=nrow * ncol,
        nper=1,
        modflow_config=_coerce_modflow6_config(None),
        _evt_rate_payload={0: 1.0e-8},  # uniform routed deficit (m/s)
    ), mesh


def test_evt_skips_lake_cells() -> None:
    model, mesh = _evt_model()
    # lake_cell_ids is passed explicitly (not read off the model) so the masking
    # does not depend on build ordering.
    evt_spd = build_evt_stress_period_data(
        model,
        mesh,
        ocean_support_mask=np.zeros(mesh.n_cells, dtype=bool),
        stream_support_mask=np.zeros(mesh.n_cells, dtype=bool),
        lake_cell_ids=[2, 4],
    )
    assert evt_spd is not None
    cells_with_evt = {int(entry[1]) for entry in evt_spd[0]}
    # Lake cells carry no aquifer EVT record.
    assert 2 not in cells_with_evt
    assert 4 not in cells_with_evt
    # Every other cell does get one.
    assert cells_with_evt == {0, 1, 3, 5}


def test_evt_without_lake_cells_covers_every_cell() -> None:
    model, mesh = _evt_model()
    evt_spd = build_evt_stress_period_data(
        model,
        mesh,
        ocean_support_mask=np.zeros(mesh.n_cells, dtype=bool),
        stream_support_mask=np.zeros(mesh.n_cells, dtype=bool),
    )
    assert evt_spd is not None
    assert {int(entry[1]) for entry in evt_spd[0]} == set(range(mesh.n_cells))
