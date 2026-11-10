"""Unit tests for ``hmp run`` CLI subcommand dispatch.

The dispatcher is driven by mandatory ``[workflow].mode`` in the TOML."""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND
from hydromodpy.cli.main import main
from hydromodpy.config.loading import load
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.project.dispatch import workflow as project_workflow
from hydromodpy.project.request import RunOutcome


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _outcome(name: str = "test", sim_id: str = "abc", **fields) -> RunOutcome:
    """The outcome of a run, as ``run_simulation`` gives it back."""
    given = {
        "name": name,
        "run_dir": Path("runs") / name,
        "sim_id": sim_id,
        "request_id": "request",
        "status": "completed",
        "identical_to": None,
        "project_root": Path("."),
        **fields,
    }
    return RunOutcome(**given)


def _simulation(monkeypatch, captured: dict, outcome: RunOutcome | None = None) -> None:
    """Stand in for the simulation runner: record the request and the base it is given."""

    def fake_run(request, *, base, environment=None, replay_of=None):
        captured.update(request=request, base=base, environment=environment, replay_of=replay_of)
        return outcome or _outcome()

    monkeypatch.setattr(project_workflow, "run_simulation", fake_run)


SIMULATION = '[workflow]\nmode = "simulation"\n[workspace]\n[simulation]\nname = "test"\n'


def test_hmp_run_dispatches_simulation_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=simulation gives the request of the file to run_simulation."""
    config = _write_toml(tmp_path / "config.toml", SIMULATION)
    captured: dict = {}
    _simulation(monkeypatch, captured)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    request = captured["request"]
    assert request.config["workflow"] == {"mode": "simulation"}
    assert request.form == "toml"
    assert request.source.endswith("config.toml")
    # The file is its own anchor: the project root above it, no variable, no option.
    assert captured["base"] == tmp_path.resolve()
    # --no-display was not passed so the CLI forwards no_display=False.
    assert request.no_display is False
    # The request was read as a draft by the command, and the run it hands over is none.
    assert request.dry_run is False
    assert captured["replay_of"] is None


def test_hmp_run_forwards_no_display_flag(monkeypatch, tmp_path) -> None:
    """``hmp run --no-display`` must reach the request."""
    config = _write_toml(tmp_path / "config.toml", SIMULATION)
    captured: dict = {}
    _simulation(monkeypatch, captured)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--no-display"])

    main()

    assert captured["request"].no_display is True


def test_hmp_run_rejects_removed_checkpoint_flag(monkeypatch, tmp_path) -> None:
    """``--checkpoint`` was removed with the pickle layer."""
    config = _write_toml(tmp_path / "config.toml", SIMULATION)
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
    _simulation(monkeypatch, captured)
    monkeypatch.setenv("HMP_SET_modflow6__runtime__mf6_ims_complexity", "COMPLEX")
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

    request = captured["request"]
    # ``[modflow6]`` moved to ``[solver.modflow6]`` in 2.1.0: each file is migrated on its
    # own. The document holds the base and its overlay, and ``--set`` rides beside it, the
    # environment winning over it, as the loader applies them last.
    assert request.config["solver"]["modflow6"]["runtime"]["mf6_ims_complexity"] == "MODERATE"
    assert "modflow6" not in request.config
    assert request.config["simulation"]["name"] == "base"
    assert request.set == {"modflow6.runtime.mf6_ims_complexity": "COMPLEX"}
    assert request.overlays == ("overlay.toml",)
    assert request.overrides() == {
        "solver.modflow6.runtime.mf6_ims_complexity": "COMPLEX",
        "overlay": ["overlay.toml"],
    }
    # Nothing is written beside the file the user named.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["config.toml", "overlay.toml"]


def test_hmp_run_resume_forwards_run_id(monkeypatch, tmp_path) -> None:
    """``--resume`` propagates a run_id to the simulation dispatcher."""
    config = _write_toml(tmp_path / "config.toml", SIMULATION)
    captured: dict = {}
    _simulation(monkeypatch, captured)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--resume", "run-1"])

    main()

    assert captured["request"].resume == "run-1"


def test_hmp_run_forwards_step_controls_to_simulation_workflow(monkeypatch, tmp_path) -> None:
    """Pipeline step controls must reach only the simulation dispatcher."""
    config = _write_toml(tmp_path / "config.toml", SIMULATION)
    captured: dict = {}
    _simulation(monkeypatch, captured)
    monkeypatch.setattr(
        "sys.argv",
        ["hmp", "run", str(config), "--from", "setup", "--until", "solve"],
    )

    main()

    assert captured["request"].from_step == "setup"
    assert captured["request"].until_step == "solve"
    assert captured["base"] == tmp_path.resolve()


def test_hmp_run_names_the_base_by_argument(monkeypatch, tmp_path) -> None:
    """``--base`` is the folder the run is written in, whatever the folder of the file."""
    config = _write_toml(tmp_path / "config.toml", SIMULATION)
    project = tmp_path / "elsewhere"
    project.mkdir()
    captured: dict = {}
    _simulation(monkeypatch, captured)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--base", str(project)])

    main()

    assert captured["base"] == project.resolve()


def test_hmp_run_takes_the_project_w_names_as_its_base(monkeypatch, tmp_path) -> None:
    """``-w`` is the base given by argument: no variable of the environment carries it."""
    config = _write_toml(tmp_path / "config.toml", SIMULATION)
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")
    captured: dict = {}
    _simulation(monkeypatch, captured)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "-w", str(project)])

    main()

    assert captured["base"] == project.resolve()


def test_hmp_run_plays_a_json_request(monkeypatch, tmp_path) -> None:
    """A ``.json`` file is a run request, and the base is its project root or ``--base``."""
    import json

    request_file = tmp_path / "request.json"
    request_file.write_text(
        json.dumps(
            {
                "schema": "hydromodpy.request.v1",
                "config": {"workflow": {"mode": "simulation"}, "simulation": {"name": "by_json"}},
                "name": "by_json",
            }
        ),
        encoding="utf-8",
    )
    captured: dict = {}
    _simulation(monkeypatch, captured)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(request_file), "--base", str(tmp_path)])

    main()

    assert captured["request"].name == "by_json"
    assert captured["request"].config["simulation"] == {"name": "by_json"}
    assert captured["base"] == tmp_path.resolve()


def test_hmp_run_refuses_an_overlay_with_a_json_request(monkeypatch, tmp_path, capsys) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(
        '{"schema": "hydromodpy.request.v1", "config": {"workflow": {"mode": "simulation"}}}',
        encoding="utf-8",
    )
    overlay = _write_toml(tmp_path / "overlay.toml", "[simulation]\n")
    monkeypatch.setattr(
        "sys.argv", ["hmp", "run", str(request_file), "--overlay", str(overlay), "--base", "."]
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_CONFIG
    assert "--overlay merges a TOML file into a TOML file" in capsys.readouterr().err


def test_hmp_run_says_what_a_skipped_run_gave_back(monkeypatch, tmp_path, capsys) -> None:
    config = _write_toml(tmp_path / "config.toml", SIMULATION)
    captured: dict = {}
    _simulation(monkeypatch, captured, _outcome(name="test.v2", identical_to="test"))
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    err = capsys.readouterr().err
    assert "Config identical to completed run 'test'" in err
    assert "Re-run with --force to run it again." in err


def test_hmp_run_gives_the_mesh_summary_of_a_run_in_its_json_result(
    monkeypatch, tmp_path, capsys
) -> None:
    """The summary of a mesh lives in memory only: the command hands it on as 2.0 did."""
    import json

    config = _write_toml(tmp_path / "config.toml", SIMULATION)
    summary = {"engine": "gmsh", "product_key": "k1"}
    _simulation(monkeypatch, {}, _outcome(mesh_summary=summary))
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--format", "json"])

    main()

    result = json.loads(capsys.readouterr().out)["data"]["result"]
    assert (result["engine"], result["product_key"], result["name"]) == ("gmsh", "k1", "test")


def test_hmp_run_rejects_step_controls_for_non_simulation_workflow(monkeypatch, tmp_path) -> None:
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy_nelder_mead"\n',
    )

    called = False

    def fake_run(request, *, base, environment=None):
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

    def fake_run(request, *, base, environment=None):
        captured["request"] = request
        captured["base"] = Path(base)
        captured["environment"] = environment
        captured["run_called"] = True
        return SimpleNamespace(to_dict=lambda: {"mode": "data_overview"})

    monkeypatch.setitem(project_workflow.DISPATCH, "overview", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["request"].source.endswith("overview.toml")
    assert captured["base"] == tmp_path.resolve()
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

    def fake_run(request, *, base, environment=None):
        captured["request"] = request
        captured["base"] = Path(base)
        captured["environment"] = environment
        captured["run_called"] = True
        return {"mode": "calibration"}

    monkeypatch.setitem(project_workflow.DISPATCH, "calibration", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["request"].source.endswith("calib.toml")
    assert captured["base"] == tmp_path.resolve()
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


def test_overview_config_respects_the_base_argument(tmp_path: Path) -> None:
    redirected_project_root = tmp_path / "redirected_project_root"

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

    cfg = load(toml_path, redirected_project_root)

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
