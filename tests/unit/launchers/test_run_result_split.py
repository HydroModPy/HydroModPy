"""Unit tests for explicit RunResult setup/data/results scopes."""

from pathlib import Path
from types import SimpleNamespace

from launchers.run_result import RunResult


def _build_result() -> RunResult:
    return RunResult(
        cfg=SimpleNamespace(),
        config_path=Path("config.toml"),
        raw_toml={},
    )


def test_run_result_setup_scope_is_explicit() -> None:
    result = _build_result()

    workspace = object()
    result.setup.workspace = workspace
    assert result.setup.workspace is workspace

    flow = object()
    result.setup.flow = flow
    assert result.setup.flow is flow


def test_run_result_data_scope_is_explicit() -> None:
    result = _build_result()

    climatic = object()
    result.data.climatic = climatic
    assert result.data.climatic is climatic

    oceanic = object()
    result.data.oceanic = oceanic
    assert result.data.oceanic is oceanic


def test_run_result_results_scope_and_lookup_helpers() -> None:
    result = _build_result()
    run = SimpleNamespace(id="flow_main__modflownwt", solver="modflownwt")
    model = object()

    result.results.process_runs_by_id = {run.id: run}
    result.results.models_by_run_id = {run.id: model}

    assert result.results.process_runs_by_id[run.id] is run
    assert result.results.models_by_run_id[run.id] is model
    assert result.get_model(run.id) is model
    assert result.get_model_for_solver("modflownwt") is model
