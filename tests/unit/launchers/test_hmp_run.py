"""The ``hmp run`` command: it reads a TOML file, picks the workflow named by
``[workflow].mode`` and hands the request to the matching runner."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_NOT_FOUND
from hydromodpy.cli.main import main
from hydromodpy.project.dispatch import workflow as project_workflow
from hydromodpy.project.request import RunOutcome

SIMULATION = '[workflow]\nmode = "simulation"\n[workspace]\n[simulation]\nname = "test"\n'


def write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def an_outcome(name: str = "test", **fields) -> RunOutcome:
    given = {
        "name": name,
        "run_dir": Path("runs") / name,
        "sim_id": "abc",
        "request_id": "request",
        "status": "completed",
        "identical_to": None,
        "project_root": Path("."),
        **fields,
    }
    return RunOutcome(**given)


def fake_simulation(monkeypatch, captured: dict, outcome: RunOutcome | None = None) -> None:
    """Replace the simulation runner by one that records the request and the base."""

    def fake_run(request, *, base, environment=None, replay_of=None):
        captured.update(request=request, base=base, environment=environment, replay_of=replay_of)
        return outcome or an_outcome()

    monkeypatch.setattr(project_workflow, "run_simulation", fake_run)


def fake_runner(captured: dict, result):
    """A runner for the overview and calibration workflows."""

    def fake_run(request, *, base, environment=None):
        captured.update(request=request, base=Path(base), environment=environment, called=True)
        return result

    return fake_run


def test_no_display_flag(monkeypatch, tmp_path) -> None:
    config = write_toml(tmp_path / "config.toml", SIMULATION)
    captured: dict = {}
    fake_simulation(monkeypatch, captured)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--no-display"])

    main()

    assert captured["request"].no_display is True


def test_overlay_set_and_env_overrides(monkeypatch, tmp_path) -> None:
    config = write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n'
        "[workspace]\n"
        '[simulation]\nname = "base"\n'
        '[modflow6.runtime]\nmf6_ims_complexity = "SIMPLE"\n',
    )
    overlay = write_toml(
        tmp_path / "overlay.toml",
        '[modflow6.runtime]\nmf6_ims_complexity = "MODERATE"\n',
    )
    captured: dict = {}
    fake_simulation(monkeypatch, captured)
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
    # ``[modflow6]`` moved to ``[solver.modflow6]`` in 2.0.0: each file is migrated on its
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


def test_step_controls(monkeypatch, tmp_path) -> None:
    config = write_toml(tmp_path / "config.toml", SIMULATION)
    captured: dict = {}
    fake_simulation(monkeypatch, captured)
    monkeypatch.setattr(
        "sys.argv", ["hmp", "run", str(config), "--from", "setup", "--until", "solve"]
    )

    main()

    assert captured["request"].from_step == "setup"
    assert captured["request"].until_step == "solve"
    assert captured["base"] == tmp_path.resolve()


def test_base_by_argument(monkeypatch, tmp_path) -> None:
    # ``--base`` is the folder the run is written in, whatever the folder of the file.
    config = write_toml(tmp_path / "config.toml", SIMULATION)
    project = tmp_path / "elsewhere"
    project.mkdir()
    captured: dict = {}
    fake_simulation(monkeypatch, captured)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--base", str(project)])

    main()

    assert captured["base"] == project.resolve()


def test_skipped_run_message(monkeypatch, tmp_path, capsys) -> None:
    config = write_toml(tmp_path / "config.toml", SIMULATION)
    fake_simulation(monkeypatch, {}, an_outcome(name="test.v2", identical_to="test"))
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    err = capsys.readouterr().err
    assert "Config identical to completed run 'test'" in err
    assert "Re-run with --force to run it again." in err


def test_mesh_summary_in_json_result(monkeypatch, tmp_path, capsys) -> None:
    # The summary of a mesh lives in memory only: the command hands it on as 2.0 did.
    config = write_toml(tmp_path / "config.toml", SIMULATION)
    summary = {"engine": "gmsh", "product_key": "k1"}
    fake_simulation(monkeypatch, {}, an_outcome(mesh_summary=summary))
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--format", "json"])

    main()

    result = json.loads(capsys.readouterr().out)["data"]["result"]
    assert (result["engine"], result["product_key"], result["name"]) == ("gmsh", "k1", "test")


def test_overview_workflow(monkeypatch, tmp_path) -> None:
    config = write_toml(
        tmp_path / "overview.toml",
        '[workflow]\nmode = "overview"\n[workspace]\n[overview]\nname = "test"\n',
    )
    captured: dict = {}
    result = SimpleNamespace(to_dict=lambda: {"mode": "data_overview"})
    monkeypatch.setattr(project_workflow, "run_overview", fake_runner(captured, result))
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["request"].source.endswith("overview.toml")
    assert captured["base"] == tmp_path.resolve()
    assert captured["called"] is True
    assert captured["environment"] is not None


def test_calibration_workflow(monkeypatch, tmp_path) -> None:
    config = write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy_nelder_mead"\n',
    )
    captured: dict = {}
    runner = fake_runner(captured, {"mode": "calibration"})
    monkeypatch.setitem(project_workflow.DISPATCH, "calibration", runner)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["request"].source.endswith("calib.toml")
    assert captured["base"] == tmp_path.resolve()
    assert captured["called"] is True
    assert captured["environment"] is not None


def test_missing_file_is_refused(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(tmp_path / "does_not_exist.toml")])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_NOT_FOUND


def test_overlay_with_json_request_is_refused(monkeypatch, tmp_path, capsys) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(
        '{"schema": "hydromodpy.request.v1", "config": {"workflow": {"mode": "simulation"}}}',
        encoding="utf-8",
    )
    overlay = write_toml(tmp_path / "overlay.toml", "[simulation]\n")
    monkeypatch.setattr(
        "sys.argv", ["hmp", "run", str(request_file), "--overlay", str(overlay), "--base", "."]
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_CONFIG
    assert "--overlay merges a TOML file into a TOML file" in capsys.readouterr().err


# (file name, content, part of the message that names the fix)
REFUSED_FILES = [
    pytest.param(
        "mesh.toml",
        '[workflow]\nmode = "mesh"\n[workspace]\n[mesh]\ncell_size = 200\n',
        "",
        id="removed mesh workflow",
    ),
    pytest.param(
        "no_workflow.toml",
        '[workspace]\n[simulation]\nname = "test"\n',
        "",
        id="no workflow mode",
    ),
    pytest.param(
        "comparison_scalar.toml",
        'workflow = "comparison"\n[comparison]\nbase_simulation_config = "base.toml"\n',
        "",
        id="workflow given as a scalar",
    ),
    pytest.param(
        "bad_workflow.toml",
        '[workflow]\nmode = "not_a_workflow"\n[workspace]\n',
        "",
        id="unknown workflow mode",
    ),
    pytest.param(
        "prototype.py",
        "print('prototype')\n",
        "Run the script with python directly.",
        id="python script",
    ),
]


@pytest.mark.parametrize(("name", "content", "message"), REFUSED_FILES)
def test_refused_files(monkeypatch, tmp_path, capsys, name, content, message) -> None:
    config = write_toml(tmp_path / name, content)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == EXIT_CONFIG
    assert message in capsys.readouterr().err
