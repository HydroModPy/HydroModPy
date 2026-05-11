from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.export_payload import build_state_history_export_payload


def test_state_history_export_payload_includes_solver_residual_history() -> None:
    state = BoussinesqState.from_runtime(
        head_m=np.asarray([10.0]),
        saturated_thickness_m=np.asarray([1.0]),
        residual_history_m3_s=np.asarray([[0.0], [0.12]]),
    )

    payload = build_state_history_export_payload(state)

    np.testing.assert_allclose(payload["residual_history_m3_s"], [[0.0], [0.12]])
