"""Unit tests for the run store a persisted run hands to its launcher.

The runner keeps the products of one run in ``execution.solver_runs``, and a
step that opens the store passes the handle to the launcher it drives. The
``hand_off`` of a transport run that reads ``face_flow``, MT3DMS among them,
is read in ``tests/unit/solver/base/test_runner.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.solver.base.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.base.runner import SimulationRunner


def test_runner_records_mesh_process_without_solver_adapter(monkeypatch) -> None:
    def _no_adapter(process_type, solver_name):
        raise AssertionError("mesh process should not request a solver adapter")

    monkeypatch.setattr(solvers, "create", _no_adapter)
    setup = SimpleNamespace(workspace=None, settings=None, geographic=None, domain=None)
    setup.mesh_summary = {"output_mesh": "mesh.msh", "n_cells": 12}
    state = SimpleNamespace(
        cfg=None, setup=setup, execution=SimpleNamespace(solver_runs={}), sim_id=None
    )
    plan = SimulationPlan(
        name="mesh-only",
        description="mesh-only",
        runs=(
            ProcessRun(
                id="mesh_main::catchment",
                process_id="mesh_main",
                process_type="mesh",
                solver="catchment",
                backend="catchment",
            ),
        ),
    )

    SimulationRunner().execute(plan, state)

    # A mesh run materializes a mesh, not a model: its run carries no solver
    # model, and what it built is execution metadata.
    assert state.execution.solver_runs["mesh_main::catchment"].solver_model is None
    assert state.execution.solver_runs["mesh_main::catchment"].metrics == {
        "backend": "catchment",
        "summary": {"output_mesh": "mesh.msh", "n_cells": 12},
    }
