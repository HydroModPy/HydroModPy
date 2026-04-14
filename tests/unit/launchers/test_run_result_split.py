"""Unit tests for explicit launcher state setup/data/execution scopes."""

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.core.state.run_state import LauncherRunState


def _build_state() -> LauncherRunState:
    return LauncherRunState(
        cfg=SimpleNamespace(),
        config_path=Path("config.toml"),
        raw_toml={},
    )


def test_run_state_setup_scope_is_explicit() -> None:
    result = _build_state()

    workspace = object()
    result.setup.workspace = workspace
    assert result.setup.workspace is workspace

    flow = object()
    result.setup.flow = flow
    assert result.setup.flow is flow


def test_run_state_data_scope_is_explicit() -> None:
    result = _build_state()

    climatic = object()
    result.loaded_data.climatic = climatic
    assert result.loaded_data.climatic is climatic

    oceanic = object()
    result.loaded_data.oceanic = oceanic
    assert result.loaded_data.oceanic is oceanic


def test_run_state_results_scope_and_lookup_helpers() -> None:
    result = _build_state()
    run = SimpleNamespace(id="flow_main__modflownwt", solver="modflownwt")
    model = object()

    result.execution.process_runs_by_id = {run.id: run}
    result.execution.models_by_run_id = {run.id: model}

    assert result.execution.process_runs_by_id[run.id] is run
    assert result.execution.models_by_run_id[run.id] is model
    assert result.get_model(run.id) is model
    assert result.get_model_for_solver("modflownwt") is model



def test_run_state_loaded_data_and_execution_scopes_are_mutable() -> None:
    result = _build_state()
    climatic = object()
    result.loaded_data.climatic = climatic
    assert result.loaded_data.climatic is climatic

    run = SimpleNamespace(id="flow_main__modflownwt", solver="modflownwt")
    model = object()
    result.execution.process_runs_by_id = {run.id: run}
    result.execution.models_by_run_id = {run.id: model}
    assert result.execution.models_by_run_id[run.id] is model
