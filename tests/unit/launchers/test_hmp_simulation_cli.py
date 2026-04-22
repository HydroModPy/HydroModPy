"""Unit tests for ``hmp run`` CLI subcommand dispatch.

The dispatcher is driven by a mandatory top-level ``workflow = "..."``
field declared in the TOML (no implicit section-based detection).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy._cli import main
from hydromodpy._cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_hmp_run_dispatches_simulation_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=simulation dispatches to run_simulation."""
    config = _write_toml(
        tmp_path / "config.toml",
        'workflow = "simulation"\n[workspace]\nproject_root = "."\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setattr("hydromodpy._cli.workflows.run_simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True
    # --no-display was not passed so the CLI forwards no_display=False.
    assert captured["kwargs"].get("no_display") is False


def test_hmp_run_forwards_no_display_flag(monkeypatch, tmp_path) -> None:
    """``hmp run --no-display`` must reach run_simulation(no_display=True)."""
    config = _write_toml(
        tmp_path / "config.toml",
        'workflow = "simulation"\n[workspace]\nproject_root = "."\n[simulation]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path, **kwargs):
        captured["kwargs"] = kwargs
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setattr("hydromodpy._cli.workflows.run_simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config), "--no-display"])

    main()

    assert captured["kwargs"].get("no_display") is True


def test_hmp_run_dispatches_overview_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=overview dispatches to run_overview."""
    config = _write_toml(
        tmp_path / "overview.toml",
        'workflow = "overview"\n[workspace]\nproject_root = "."\n[overview]\nname = "test"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "data_overview"}

    monkeypatch.setattr("hydromodpy._cli.workflows.run_overview", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_dispatches_mesh_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=mesh dispatches to run_mesh."""
    config = _write_toml(
        tmp_path / "mesh.toml",
        'workflow = "mesh"\n'
        '[workspace]\nproject_root = "."\n'
        "[mesh_catchment]\nelement_size = 200\n",
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "mesh"}

    monkeypatch.setattr("hydromodpy._cli.workflows.run_mesh", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_dispatches_calibration_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=calibration dispatches to run_calibration."""
    config = _write_toml(
        tmp_path / "calib.toml",
        'workflow = "calibration"\n[calibration]\nmethod = "scipy"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "calibration"}

    monkeypatch.setattr("hydromodpy._cli.workflows.run_calibration", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_dispatches_batch_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=batch dispatches to run_batch."""
    config = _write_toml(
        tmp_path / "batch.toml",
        'workflow = "batch"\n[batch]\ncatalog_path = "sites.csv"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "batch"}

    monkeypatch.setattr("hydromodpy._cli.workflows.run_batch", fake_run)
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


def test_hmp_run_crashes_on_unknown_workflow_value(monkeypatch, tmp_path) -> None:
    """``hmp run`` rejects a workflow value outside the Literal set."""
    config = _write_toml(
        tmp_path / "bad_workflow.toml",
        'workflow = "comparison"\n[workspace]\nproject_root = "."\n',
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
