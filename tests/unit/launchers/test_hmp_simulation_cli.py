"""Unit tests for ``hmp run`` CLI subcommand with auto-detect dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy._cli import main


def test_hmp_run_dispatches_simulation_via_detect_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run config.toml`` with a simulation TOML dispatches to run_simulation."""
    config = tmp_path / "config.toml"
    config.write_text(
        '[workspace]\nproject_root = "."\n[simulation]\nname = "test"\n',
        encoding="utf-8",
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"name": "test", "sim_id": "abc"}

    monkeypatch.setattr("hydromodpy._cli.workflows.run_simulation", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_dispatches_overview_via_detect_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run overview.toml`` with an overview TOML dispatches to run_overview."""
    config = tmp_path / "overview.toml"
    config.write_text(
        '[workspace]\nproject_root = "."\n[overview]\nname = "test"\n',
        encoding="utf-8",
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


def test_hmp_run_dispatches_mesh_via_detect_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run mesh.toml`` with a mesh_catchment TOML dispatches to run_mesh."""
    config = tmp_path / "mesh.toml"
    config.write_text(
        '[workspace]\nproject_root = "."\n[mesh_catchment]\nelement_size = 200\n',
        encoding="utf-8",
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


def test_hmp_run_exits_on_missing_file(monkeypatch, tmp_path) -> None:
    from hydromodpy._cli.helpers import EXIT_NOT_FOUND

    missing = tmp_path / "does_not_exist.toml"
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(missing)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == EXIT_NOT_FOUND


def test_hmp_run_dispatches_calibration_via_detect_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with a calibration TOML dispatches to run_calibration."""
    config = tmp_path / "calib.toml"
    config.write_text(
        '[calibration]\nmethod = "scipy"\n',
        encoding="utf-8",
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
