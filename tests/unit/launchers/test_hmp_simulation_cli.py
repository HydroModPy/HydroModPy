"""Unit tests for ``hmp run`` CLI subcommand dispatch.

The dispatcher is driven by a mandatory top-level ``workflow = "..."``
field declared in the TOML (no implicit section-based detection).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.cli import main
from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND
from hydromodpy.workflow import dispatch as workflow_dispatch


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_hmp_run_dispatches_simulation_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=simulation dispatches to run_simulation."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\nproject_root = "."\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True
    # --no-display was not passed so the CLI forwards no_display=False.
    assert captured["kwargs"].get("no_display") is False
    assert captured["kwargs"].get("checkpoint") is False


def test_hmp_run_forwards_no_display_flag(monkeypatch, tmp_path) -> None:
    """``hmp run --no-display`` must reach run_simulation(no_display=True)."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\nproject_root = "."\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--no-display"])

    main()

    assert captured["kwargs"].get("no_display") is True


def test_hmp_run_forwards_checkpoint_flag(monkeypatch, tmp_path) -> None:
    """``hmp run --checkpoint`` must opt into checkpoint persistence."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\nproject_root = "."\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--checkpoint"])

    main()

    assert captured["kwargs"].get("checkpoint") is True


def test_hmp_run_resume_enables_checkpoint(monkeypatch, tmp_path) -> None:
    """``--resume`` implies checkpoint reads even without ``--checkpoint``."""
    config = _write_toml(
        tmp_path / "config.toml",
        '[workflow]\nmode = "simulation"\n[workspace]\nproject_root = "."\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--resume", "run-1"])

    main()

    assert captured["kwargs"].get("checkpoint") is True


def test_hmp_run_dispatches_overview_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=overview dispatches to run_overview."""
    config = _write_toml(
        tmp_path / "overview.toml",
        '[workflow]\nmode = "overview"\n[workspace]\nproject_root = "."\n[overview]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "data_overview"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "overview", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_dispatches_mesh_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=mesh dispatches to run_mesh."""
    config = _write_toml(
        tmp_path / "mesh.toml",
        '[workflow]\nmode = "mesh"\n'
        '[workspace]\nproject_root = "."\n'
        "[mesh_catchment]\nelement_size = 200\n",
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "mesh"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "mesh", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_dispatches_calibration_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=calibration dispatches to run_calibration."""
    config = _write_toml(
        tmp_path / "calib.toml",
        '[workflow]\nmode = "calibration"\n[calibration]\nmethod = "scipy"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "calibration"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "calibration", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_dispatches_batch_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=batch dispatches to run_batch."""
    config = _write_toml(
        tmp_path / "batch.toml",
        '[workflow]\nmode = "batch"\n[batch]\ncatalog_path = "sites.csv"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "batch"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "batch", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_crashes_when_workflow_field_missing(monkeypatch, tmp_path) -> None:
    """``hmp run`` refuses a TOML that does not declare ``workflow = "..."``."""
    config = _write_toml(
        tmp_path / "no_workflow.toml",
        '[workspace]\nproject_root = "."\n[simulation]\nname = "test"\n',
    )
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == EXIT_CONFIG


def test_hmp_run_dispatches_comparison_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=comparison dispatches to run_comparison."""
    config = _write_toml(
        tmp_path / "comparison.toml",
        '[workflow]\nmode = "comparison"\n[comparison]\nbase_simulation_config = "base.toml"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "comparison"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "comparison", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_dispatches_testbed_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=testbed dispatches to run_testbed."""
    config = _write_toml(
        tmp_path / "testbed.toml",
        '[workflow]\nmode = "testbed"\n[testbed]\nid = "demo"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "testbed"}

    monkeypatch.setitem(workflow_dispatch.DISPATCH, "testbed", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_crashes_on_unknown_workflow_value(monkeypatch, tmp_path) -> None:
    """``hmp run`` rejects a workflow value outside the known set."""
    config = _write_toml(
        tmp_path / "bad_workflow.toml",
        '[workflow]\nmode = "not_a_workflow"\n[workspace]\nproject_root = "."\n',
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
    assert "hmp dev run-script" in err


def test_hmp_dev_run_script_executes_python_scripts(monkeypatch, tmp_path) -> None:
    script = tmp_path / "prototype.py"
    script.write_text("print('prototype')\n", encoding="utf-8")
    captured: dict = {}

    def fake_run(cmd, cwd):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("hydromodpy.cli.commands.dev.subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["hmp", "dev", "run-script", str(script), "--case", "demo"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert captured["cmd"][1:] == [str(script.resolve()), "--case", "demo"]
    assert captured["cwd"] == str(tmp_path)
