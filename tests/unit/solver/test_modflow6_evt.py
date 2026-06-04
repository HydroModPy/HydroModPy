from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders import (
    build_evt_stress_period_data,
    extract_evt_payload_2d,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

from ._test_modflow6_boundary_conditions_builders import _build_model


@pytest.mark.parametrize(
    ("recharge_2d", "expected_clipped", "expected_evt"),
    [
        pytest.param(
            {
                0: np.array([1.0e-6, -2.0e-6], dtype=float),
                1: np.array([-3.0e-6, 4.0e-6], dtype=float),
            },
            {
                0: np.array([1.0e-6, 0.0], dtype=float),
                1: np.array([0.0, 4.0e-6], dtype=float),
            },
            {
                0: np.zeros(2, dtype=float),
                1: np.array([3.0e-6, 0.0], dtype=float),
            },
            id="test_modflow6_extracts_evt_payload_from_negative_2d_recharge",
        ),
        pytest.param(
            {
                0: np.asarray([1.0, -2.0], dtype=float),
                1: np.asarray([-3.0, 4.0], dtype=float),
            },
            {
                0: np.asarray([1.0, 0.0], dtype=float),
                1: np.asarray([0.0, 4.0], dtype=float),
            },
            {
                0: np.asarray([0.0, 0.0], dtype=float),
                1: np.asarray([3.0, 0.0], dtype=float),
            },
            id="test_modflow6_flow_adapter_extracts_evt_payload_from_negative_2d_recharge",
        ),
    ],
)
def test_modflow6_extracts_evt_payload_from_negative_2d_recharge(
    recharge_2d: dict[int, np.ndarray],
    expected_clipped: dict[int, np.ndarray],
    expected_evt: dict[int, np.ndarray],
) -> None:
    clipped_rch, evt_data = extract_evt_payload_2d(recharge_2d, True)

    assert evt_data is not None
    np.testing.assert_allclose(clipped_rch[0], expected_clipped[0])
    np.testing.assert_allclose(clipped_rch[1], expected_clipped[1])
    np.testing.assert_allclose(evt_data[0], expected_evt[0])
    np.testing.assert_allclose(evt_data[1], expected_evt[1])


def test_modflow6_builds_evt_stress_period_data_from_routed_payload() -> None:
    model = _build_model()
    model.flow_regime = "transient"
    model._evt_rate_payload = {0: 0.0, 1: 1.0e-6}
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    evt_spd = build_evt_stress_period_data(
        model,
        solver_mesh,
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )

    assert evt_spd is not None
    assert evt_spd[0] == []
    assert len(evt_spd[1]) == 6
    assert evt_spd[1][0] == [
        0,
        0,
        pytest.approx(10.0),
        pytest.approx(1.0e-6),
        pytest.approx(1.0),
    ]
