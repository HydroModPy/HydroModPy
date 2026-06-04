"""WP6 - the steady spin-up period carries the time-mean recharge and EVT deficit.

The routing keys on the steady flag (model.steady), not kper == 0: a steady
period carries the per-cell time mean of the positive recharge and of the routed
deficit; a transient period (including a transient first period) keeps its own
positive/negative split. MF6 and MODFLOW-NWT share the routing helper.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.recharge import (
    build_evt_stress_period_data,
    recharge_to_spd,
)
from hydromodpy.solver.modflow_common.recharge_evt_routing import route_negative_recharge_to_evt
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

from ._test_modflow6_boundary_conditions_builders import _build_model

_MAPPING = {
    0: np.array([2.0e-6, -1.0e-6]),
    1: np.array([4.0e-6, 4.0e-6]),
    2: np.array([-3.0e-6, -2.0e-6]),
}


def test_steady_period_routed_evt_carries_mean_deficit() -> None:
    clipped, evt = route_negative_recharge_to_evt(_MAPPING, steady=[True, False, False])
    # Steady period 0: per-cell time mean of positives / deficits.
    np.testing.assert_allclose(clipped[0], [2.0e-6, (0.0 + 4.0e-6 + 0.0) / 3.0])
    np.testing.assert_allclose(evt[0], [1.0e-6, 1.0e-6])
    # Transient periods keep their own split.
    np.testing.assert_allclose(clipped[2], [0.0, 0.0])
    np.testing.assert_allclose(evt[2], [3.0e-6, 2.0e-6])


def test_evt_routing_keyed_on_steady_flag_not_period_index() -> None:
    clipped, evt = route_negative_recharge_to_evt(_MAPPING, steady=[False, False, False])
    # All transient: period 0 keeps its OWN split, not zeroed.
    np.testing.assert_allclose(clipped[0], [2.0e-6, 0.0])
    np.testing.assert_allclose(evt[0], [0.0, 1.0e-6])


def test_routed_evt_unit_conversion_factor() -> None:
    # 8.64 mm/day = 1.0e-7 m/s; -86.4 mm/day deficit = 1.0e-6 m/s.
    mapping = {0: np.array([1.0e-7]), 1: np.array([-1.0e-6])}
    clipped, evt = route_negative_recharge_to_evt(mapping, steady=[True, False])
    np.testing.assert_allclose(clipped[0], [(1.0e-7 + 0.0) / 2.0])
    np.testing.assert_allclose(evt[0], [(0.0 + 1.0e-6) / 2.0])


def test_steady_period_recharge_uses_first_clim_mean() -> None:
    model = _build_model()
    model.nper = 3
    model.ncpl = 2
    model.steady = np.array([True, False, False])
    model.recharge = np.array([1.0e-7, 2.0e-7, 3.0e-7])

    model.first_clim = "mean"
    spd = recharge_to_spd(model)
    np.testing.assert_allclose(spd[0], [2.0e-7, 2.0e-7])  # mean over the 3 periods
    np.testing.assert_allclose(spd[1], [2.0e-7, 2.0e-7])
    np.testing.assert_allclose(spd[2], [3.0e-7, 3.0e-7])

    model.first_clim = "first"
    assert recharge_to_spd(model)[0][0] == pytest.approx(1.0e-7)

    model.recharge = np.array([5.0e-8, 2.0e-7, 3.0e-7])
    model.first_clim = 5.0e-8
    assert recharge_to_spd(model)[0][0] == pytest.approx(5.0e-8)


def _two_layer_mesh(inactive_mask: np.ndarray) -> SolverMesh:
    ncpl = 3
    vertices = np.array(
        [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [1, 1], [2, 1], [3, 1]], dtype=float
    )
    conn = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6]], dtype=int)
    return SolverMesh(
        planar_mesh=HydroMesh(
            vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),)
        ),
        top=np.full(ncpl, 10.0),
        botm=np.array([[5.0, 5.0, 5.0], [0.0, 0.0, 0.0]]),
        inactive_mask=inactive_mask,
    )


def test_evt_cell_targets_uppermost_active_layer_multilayer_disv() -> None:
    # cell0 active in layer 0; cell1 inactive in layer 0 but active in layer 1;
    # cell2 fully inactive.
    inactive = np.array([[False, True, True], [False, False, True]])
    mesh = _two_layer_mesh(inactive)
    model = _build_model()
    model.nper = 1
    model.ncpl = 3
    model.modflow_config = model.modflow_config  # default config carries evt depth
    model._evt_rate_payload = {0: 1.0e-6}

    with pytest.warns(RuntimeWarning):
        evt_spd = build_evt_stress_period_data(
            model,
            mesh,
            ocean_support_mask=np.zeros(3, dtype=bool),
            stream_support_mask=np.zeros(3, dtype=bool),
        )
    records = {int(rec[1]): int(rec[0]) for rec in evt_spd[0]}  # cell_id -> layer
    assert records == {0: 0, 1: 1}  # cell2 (fully inactive) has no record


def test_mf6_and_nwt_share_routing_helper() -> None:
    from hydromodpy.solver.modflow_nwt.nwt import _recharge_etp_payloads

    assert _recharge_etp_payloads.route_negative_recharge_to_evt is route_negative_recharge_to_evt
