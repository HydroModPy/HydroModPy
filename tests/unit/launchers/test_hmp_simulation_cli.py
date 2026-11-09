"""Unit tests for ``hmp run`` CLI subcommand dispatch.

The dispatcher is driven by mandatory ``[workflow].mode`` in the TOML."""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND
from hydromodpy.cli.main import main
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.project.dispatch import workflow as project_workflow


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_hmp_run_dispatches_simulation_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=simulation dispatches to run_simulation."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setitem(project_workflow.DISPATCH, "simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True
    # --no-display was not passed so the CLI forwards no_display=False.
    assert captured["kwargs"].get("no_display") is False
    # ``--checkpoint`` was removed with the pickle layer.
    assert "checkpoint" not in captured["kwargs"]


def test_hmp_run_forwards_no_display_flag(monkeypatch, tmp_path) -> None:
    """``hmp run --no-display`` must reach run_simulation(no_display=True)."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setitem(project_workflow.DISPATCH, "simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--no-display"])

    main()

    assert captured["kwargs"].get("no_display") is True


def test_hmp_run_rejects_removed_checkpoint_flag(monkeypatch, tmp_path) -> None:
    """``--checkpoint`` was removed with the pickle layer."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\n[simulation]\nname = "test"\n',
    )
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--checkpoint"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0


def test_hmp_run_applies_overlay_set_and_env_overrides(monkeypatch, tmp_path) -> None:
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n'
        "[workspace]\n"
        '[simulation]\nname = "base"\n'
        '[modflow6.runtime]\nmf6_ims_complexity = "SIMPLE"\n',
    )
    overlay = _write_toml(
        tmp_path / "overlay.toml",
        '[modflow6.runtime]\nmf6_ims_complexity = "MODERATE"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        path = Path(config_path)
        captured["config_path"] = path
        captured["payload"] = tomllib.loads(path.read_text(encoding="utf-8"))
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setenv("HMP_SET_modflow6__runtime__mf6_ims_complexity", "COMPLEX")
    monkeypatch.setitem(project_workflow.DISPATCH, "simulation", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "hmp",
            "run",
            str(config),
            "--overlay",
            str(overlay),
            "--set",
            "modflow6.runtime.mf6_ims_complexity=SIMPLE",
        ],
    )

    with pytest.warns(Warning, match="solver.modflow6"):
        main()

    assert captured["config_path"] != config.resolve()
    assert not captured["config_path"].exists()
    # ``[modflow6]`` moved to ``[solver.modflow6]`` in 2.1.0: each layer is migrated on its
    # own, then the environment wins over ``--set``, which wins over the overlay and the base.
    payload = captured["payload"]
    assert payload["solver"]["modflow6"]["runtime"]["mf6_ims_complexity"] == "COMPLEX"
    assert "modflow6" not in payload
    assert payload["simulation"]["name"] == "base"


def test_hmp_run_resume_forwards_run_id(monkeypatch, tmp_path) -> None:
    """``--resume`` propagates a run_id to the simulation dispatcher."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setitem(project_workflow.DISPATCH, "simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--resume", "run-1"])

    main()

    assert captured["kwargs"].get("resume") == "run-1"


def test_hmp_run_forwards_step_controls_to_simulation_workflow(monkeypatch, tmp_path) -> None:
    """Pipeline step controls must reach only the simulation dispatcher."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["config_path"] = Path(config_path)
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setitem(project_workflow.DISPATCH, "simulation", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["hmp", "run", str(config), "--from", "setup", "--until", "solve"],
    )

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["kwargs"]["from_step"] == "setup"
    assert captured["kwargs"]["until_step"] == "solve"
    assert "parallel" not in captured["kwargs"]


def test_hmp_run_rejects_step_controls_for_non_simulation_workflow(monkeypatch, tmp_path) -> None:
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy_nelder_mead"\n',
    )

    called = False

    def fake_run(config_path, environment=None):
        nonlocal called
        called = True
        return {"mode": "calibration"}

    monkeypatch.setitem(project_workflow.DISPATCH, "calibration", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--from", "setup"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_CONFIG
    assert called is False


def test_hmp_run_dispatches_overview_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=overview dispatches to run_overview."""
    config = _write_toml(
        tmp_path / "overview.toml",
        '[workflow]\nmode = "overview"\n[workspace]\n[overview]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, environment=None):
        captured["config_path"] = Path(config_path)
        captured["environment"] = environment
        captured["run_called"] = True
        return SimpleNamespace(to_dict=lambda: {"mode": "data_overview"})

    monkeypatch.setitem(project_workflow.DISPATCH, "overview", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True
    assert captured["environment"] is not None


def test_hmp_run_rejects_removed_mesh_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` no longer accepts the removed workflow=mesh value."""
    config = _write_toml(
        tmp_path / "mesh.toml",
        '[workflow]\nmode = "mesh"\n[workspace]\n[mesh]\ncell_size = 200\n',
    )

    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == EXIT_CONFIG


def test_hmp_run_dispatches_calibration_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=calibration dispatches to run_calibration."""
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy_nelder_mead"\n',
    )

    captured: dict = {}

    def fake_run(config_path, environment=None):
        captured["config_path"] = Path(config_path)
        captured["environment"] = environment
        captured["run_called"] = True
        return {"mode": "calibration"}

    monkeypatch.setitem(project_workflow.DISPATCH, "calibration", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True
    assert captured["environment"] is not None


def test_hmp_run_rejects_removed_batch_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` no longer accepts the removed workflow=batch value."""
    config = _write_toml(
        tmp_path / "batch.toml",
        '[workflow]\nmode = "batch"\n[batch]\ncatalog_path = "sites.csv"\n',
    )

    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == EXIT_CONFIG


def test_hmp_run_crashes_when_workflow_field_missing(monkeypatch, tmp_path) -> None:
    """``hmp run`` refuses a TOML that does not declare ``[workflow].mode``."""
    config = _write_toml(
        tmp_path / "no_workflow.toml",
        '[workspace]\n[simulation]\nname = "test"\n',
    )
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == EXIT_CONFIG


def test_hmp_run_rejects_scalar_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` requires the canonical ``[workflow].mode`` table."""
    config = _write_toml(
        tmp_path / "comparison_scalar.toml",
        'workflow = "comparison"\n[comparison]\nbase_simulation_config = "base.toml"\n',
    )

    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == EXIT_CONFIG


def test_hmp_run_crashes_on_unknown_workflow_value(monkeypatch, tmp_path) -> None:
    """``hmp run`` rejects a workflow value outside the known set."""
    config = _write_toml(
        tmp_path / "bad_workflow.toml",
        '[workflow]\nmode = "not_a_workflow"\n[workspace]\n',
    )
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == EXIT_CONFIG


def test_hmp_run_exits_on_missing_file(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "does_not_exist.toml"
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(missing)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == EXIT_NOT_FOUND


def test_hmp_run_rejects_python_scripts(monkeypatch, tmp_path, capsys) -> None:
    script = tmp_path / "prototype.py"
    script.write_text("print('prototype')\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(script)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "Run the script with python directly." in err


def test_overview_config_respects_project_root_env_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    redirected_project_root = tmp_path / "redirected_project_root"
    monkeypatch.setenv(
        "HMP_PROJECT_ROOT",
        str(redirected_project_root),
    )

    toml_content = f"""\
[workflow]
mode = "simulation"
[workspace]
root = "{tmp_path}"

[site]
name = "site_a"

[geographic]
[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 1.0
y_outlet = 2.0
snap_dist = "150 m"
buff_area = "20%"

[overview]
name = "Test"
"""
    toml_path = tmp_path / "overview.toml"
    toml_path.write_text(toml_content, encoding="utf-8")

    cfg = HydroModPyConfig.from_toml(toml_path)

    assert cfg.workspace.project_root == redirected_project_root.resolve()
    assert cfg.overview is not None
    assert cfg.overview.name == "Test"


def _build_state() -> WorkflowContext:
    return WorkflowContext(
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


def test_run_state_results_scope_holds_what_the_runner_recorded() -> None:
    result = _build_state()
    run = SimpleNamespace(id="flow_main__modflow_nwt", solver="modflow_nwt")
    solver_run = object()

    result.execution.process_runs_by_id = {run.id: run}
    result.execution.solver_runs[run.id] = solver_run

    assert result.execution.process_runs_by_id[run.id] is run
    assert result.execution.solver_runs[run.id] is solver_run


def test_run_state_loaded_data_and_execution_scopes_are_mutable() -> None:
    result = _build_state()
    climatic = object()
    result.loaded_data.climatic = climatic
    assert result.loaded_data.climatic is climatic

    run = SimpleNamespace(id="flow_main__modflow_nwt", solver="modflow_nwt")
    solver_run = object()
    result.execution.process_runs_by_id = {run.id: run}
    result.execution.solver_runs[run.id] = solver_run
    assert result.execution.solver_runs[run.id] is solver_run
