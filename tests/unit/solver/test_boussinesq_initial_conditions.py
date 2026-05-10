from types import SimpleNamespace

import numpy as np

from hydromodpy.physics.flow.initial_conditions import (
    FlowInitialCondition,
    FlowInitialConditions,
)
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.forcing_resolution import BoussinesqForcingResolver
from hydromodpy.solver.steady_initial_conditions import steady_flow_copy_for_initialization


class _Config(SimpleNamespace):
    def model_copy(self, *, update):
        data = dict(self.__dict__)
        data.update(update)
        return _Config(**data)


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


def test_boussinesq_initial_state_records_head_bounds_summary(tmp_path) -> None:
    mesh = SimpleNamespace(
        n_cells=3,
        z_top_m=np.asarray([5.0, 5.0, 5.0], dtype=float),
        z_bottom_m=np.asarray([1.0, 1.0, 1.0], dtype=float),
    )
    flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(
            h=FlowInitialCondition(id="h", type="custom", value=6.0, units="m")
        )
    )
    solver = Boussinesq(
        mesh_bundle=None,
        mesh=mesh,
        flow=flow,
        domain=SimpleNamespace(),
        time_grid=None,
        model_folder=tmp_path,
        model_name="bounds_summary",
    )

    state = solver._build_initial_state()

    np.testing.assert_allclose(state.head_m, np.full(3, 6.0))
    bounds = solver.runtime_summary["initial_head_bounds"]
    assert bounds["above_top_count"] == 3
    assert bounds["below_bottom_count"] == 0
    assert bounds["max_above_top_m"] == 1.0
    assert bounds["within_bounds"] is False


def test_petsc_ts_vi_initialization_uses_regularized_steady_solve() -> None:
    flow = SimpleNamespace(
        flow_regime="transient",
        runtime_backend="petsc",
        surface_interaction_model="ts_vi_obstacle",
        initial_conditions=FlowInitialConditions(
            h=FlowInitialCondition(id="h", type="steady_state")
        ),
        sinks_sources={},
    )

    steady_flow = steady_flow_copy_for_initialization(flow)

    assert steady_flow.flow_regime == "steady"
    assert steady_flow.runtime_backend == "petsc"
    assert steady_flow.surface_interaction_model == "regularized_partition"
    assert steady_flow.initial_conditions.h.type == "top"


def test_petsc_ts_vi_initialization_reads_surface_model_from_config() -> None:
    flow = SimpleNamespace(
        flow_regime="transient",
        runtime_backend="petsc",
        config=_Config(
            flow_regime="transient",
            runtime_backend="petsc",
            surface_interaction_model="ts_vi_obstacle",
        ),
        initial_conditions=FlowInitialConditions(
            h=FlowInitialCondition(id="h", type="steady_state")
        ),
        sinks_sources={},
    )

    steady_flow = steady_flow_copy_for_initialization(flow)

    assert steady_flow.surface_interaction_model == "regularized_partition"
    assert steady_flow.config.surface_interaction_model == "regularized_partition"
    assert steady_flow.config.ic.h.type == "top"
