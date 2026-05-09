from types import SimpleNamespace

import numpy as np

from hydromodpy.physics.flow.initial_conditions import (
    FlowInitialCondition,
    FlowInitialConditions,
)
from hydromodpy.solver.boussinesq.forcing_resolution import BoussinesqForcingResolver


def test_boussinesq_steady_state_initial_condition_uses_top_as_initial_guess() -> None:
    mesh = SimpleNamespace(
        n_cells=3,
        z_top_m=np.asarray([10.0, 11.0, 12.0], dtype=float),
        z_bottom_m=np.asarray([1.0, 1.0, 1.0], dtype=float),
    )
    flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(
            h=FlowInitialCondition(id="h", type="steady_state")
        )
    )
    resolver = BoussinesqForcingResolver(mesh=mesh, flow=flow, time_grid=None)

    head = resolver.resolve_initial_head_field()

    np.testing.assert_allclose(head, mesh.z_top_m)
