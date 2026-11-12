"""The scopes of a workflow run state (setup, loaded data, execution).

Each scope holds what its stage records and gives it back unchanged."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.core.state.run_state import WorkflowContext


def a_state() -> WorkflowContext:
    return WorkflowContext(cfg=SimpleNamespace(), config_path=Path("config.toml"), raw_toml={})


def test_setup_scope() -> None:
    state = a_state()
    workspace, flow = object(), object()

    state.setup.workspace = workspace
    state.setup.flow = flow

    assert state.setup.workspace is workspace
    assert state.setup.flow is flow


def test_loaded_data_scope() -> None:
    state = a_state()
    climatic, oceanic = object(), object()

    state.loaded_data.climatic = climatic
    state.loaded_data.oceanic = oceanic

    assert state.loaded_data.climatic is climatic
    assert state.loaded_data.oceanic is oceanic


def test_execution_scope() -> None:
    state = a_state()
    run = SimpleNamespace(id="flow_main__modflow_nwt", solver="modflow_nwt")
    solver_run = object()

    state.execution.process_runs_by_id = {run.id: run}
    state.execution.solver_runs[run.id] = solver_run

    assert state.execution.process_runs_by_id[run.id] is run
    assert state.execution.solver_runs[run.id] is solver_run
