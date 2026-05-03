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


def test_hmp_run_dispatches_comparison_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=comparison dispatches to run_comparison."""
    config = _write_toml(
        tmp_path / "comparison.toml",
        'workflow = "comparison"\n[comparison]\nbase_simulation_config = "base.toml"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "comparison"}

    monkeypatch.setattr("hydromodpy._cli.workflows.run_comparison", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_dispatches_testbed_workflow(monkeypatch, tmp_path) -> None:
    """``hmp run`` with workflow=testbed dispatches to run_testbed."""
    config = _write_toml(
        tmp_path / "testbed.toml",
        'workflow = "testbed"\n'
        "[testbed]\n"
        'id = "mesh_resolution"\n'
        "\n"
        "[[testbed.variant]]\n"
        'id = "coarse"\n',
    )

    captured: dict = {}

    def fake_run(config_path):
        captured["config_path"] = Path(config_path)
        captured["run_called"] = True
        return {"mode": "testbed"}

    monkeypatch.setattr("hydromodpy._cli.workflows.run_testbed", fake_run)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    assert captured["config_path"] == config.resolve()
    assert captured["run_called"] is True


def test_hmp_run_executes_testbed_dry_plan(monkeypatch, tmp_path) -> None:
    """``hmp run`` can execute a real testbed plan without child execution."""
    config = _write_toml(
        tmp_path / "testbed.toml",
        'workflow = "testbed"\n'
        "\n"
        "[workspace]\n"
        'project_root = "mesh_outputs/base"\n'
        "\n"
        "[mesh_catchment]\n"
        'constraints_mode = "rivers_only"\n'
        "\n"
        "[testbed]\n"
        'id = "mesh_resolution"\n'
        'output_root = "outputs/testbed"\n'
        "execute = false\n"
        "\n"
        "[[testbed.variant]]\n"
        'id = "coarse"\n'
        'axis = "resolution"\n'
        "\n"
        "[testbed.variant.overlay.mesh_catchment.zone_meshing]\n"
        "global_size = 400.0\n",
    )

    monkeypatch.setattr("hydromodpy._cli.commands.run.auto_scan_workspace", lambda _: None)
    monkeypatch.setattr("hydromodpy.core.tools.display.print_hydromodpy", lambda: None)
    monkeypatch.setattr("sys.argv", ["hmp", "run", str(config)])

    main()

    output_root = tmp_path / "outputs" / "testbed"
    assert (output_root / "_generated_configs" / "coarse.toml").exists()
    assert (output_root / "testbed_plan.json").exists()
    assert (output_root / "testbed_manifest.json").exists()


def test_hmp_run_crashes_on_unknown_workflow_value(monkeypatch, tmp_path) -> None:
    """``hmp run`` rejects a workflow value outside the known set."""
    config = _write_toml(
        tmp_path / "bad_workflow.toml",
        'workflow = "not_a_workflow"\n[workspace]\nproject_root = "."\n',
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
