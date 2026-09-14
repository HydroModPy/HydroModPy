from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.physics.flow.initial_conditions import (
    FlowICBottom,
    FlowICSteadyState,
    FlowICTop,
    FlowInitialConditions,
)
from hydromodpy.solver.modflow6.builders import build_start_heads
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

from ._test_modflow6_boundary_conditions_builders import _build_model


def test_modflow6_builds_start_heads_from_typed_initial_conditions() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(h=FlowICTop(id="h")),
        boundary_conditions={},
        active_bc=[],
    )
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    strt = build_start_heads(model, solver_mesh)

    # DISV: strt shape is (nlay, ncpl)
    assert strt.shape == (1, 6)
    assert np.allclose(strt[0], top.ravel())


def test_modflow6_steady_state_initial_condition_uses_top_as_build_guess() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(h=FlowICSteadyState(id="h")),
        boundary_conditions={},
        active_bc=[],
    )
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.ones_like(top)
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    strt = build_start_heads(model, solver_mesh)

    assert strt.shape == (1, 6)
    assert np.allclose(strt[0], top.ravel())


def test_modflow6_accepts_bottom_initial_condition_name() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(h=FlowICBottom(id="h")),
        boundary_conditions={},
        active_bc=[],
    )
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_layer1 = np.array([[6.0, 6.0, 6.0], [6.0, 6.0, 6.0]], dtype=float)
    botm_layer2 = np.array([[2.0, 3.0, 4.0], [5.0, 6.0, 7.0]], dtype=float)
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_layer1, botm_layer2]),
    )

    strt = build_start_heads(model, solver_mesh)

    # DISV: strt shape is (nlay, ncpl) - all layers start at deepest botm
    assert np.allclose(strt[0], botm_layer2.ravel())


def test_read_restart_heads_reads_last_step_and_fills_inactive(tmp_path) -> None:
    """Hotstart uses the prior run's last time step; inactive cells fall back to top."""
    import zarr

    from hydromodpy.solver.modflow6.builders.initial_conditions import read_restart_heads

    prior = tmp_path / "prior.zarr"
    root = zarr.open(str(prior), mode="w")
    # two periods, two layers, three cells; the last step has one inactive (NaN) cell.
    root["head"] = np.array(
        [[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], [[1.0, 2.0, 3.0], [4.0, 5.0, np.nan]]]
    )

    strt = read_restart_heads(str(prior), nlay=2, ncpl=3, top_flat=np.array([10.0, 20.0, 30.0]))

    assert np.array_equal(strt, [[1.0, 2.0, 3.0], [4.0, 5.0, 30.0]])


def test_read_restart_heads_rejects_a_mismatched_mesh(tmp_path) -> None:
    """A cell-count mismatch raises (rather than silently reindexing)."""
    import zarr

    from hydromodpy.solver.modflow6.builders.initial_conditions import read_restart_heads

    prior = tmp_path / "prior.zarr"
    zarr.open(str(prior), mode="w")["head"] = np.zeros((1, 2, 3))

    with pytest.raises(ValueError, match="does not match"):
        read_restart_heads(str(prior), nlay=2, ncpl=5, top_flat=np.zeros(5))


def test_resolve_restart_from_reads_flow_config() -> None:
    from hydromodpy.solver.modflow6.builders.initial_conditions import resolve_restart_from

    with_source = SimpleNamespace(
        flow=SimpleNamespace(config=SimpleNamespace(restart_from=" a.zarr "))
    )
    assert resolve_restart_from(with_source) == "a.zarr"
    without = SimpleNamespace(flow=SimpleNamespace(config=SimpleNamespace(restart_from=None)))
    assert resolve_restart_from(without) is None
