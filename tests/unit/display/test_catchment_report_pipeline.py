from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.display.catchment_report.pipeline import run_catchment_report_pipeline


class _CompletedRun:
    returncode = 0
    stdout = ""
    stderr = ""

    def check_returncode(self) -> None:
        return None


def _write_report_config(config_path: Path, *, pipeline: str = "") -> None:
    config_path.write_text(
        f"""
[report]
site_label = "Test"
station_label = "Test outlet"
output_dir = "report"

[layout]
watershed_project_dir = "."
context_outputs_dir = "context"
simulation_workspace_dir = "sim_workspace"
simulation_name = "test_run"
transient_config_name = "run_test.toml"
{pipeline}
""".lstrip(),
        encoding="utf-8",
    )


def test_run_simulation_validates_expected_report_outputs(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _CompletedRun()

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        fake_run,
    )

    with pytest.raises(FileNotFoundError) as exc_info:
        run_catchment_report_pipeline(
            config_path,
            run_simulation=True,
            build_context_artifacts=False,
            build_report_html=False,
        )

    assert calls
    assert calls[0][0][-1] == "--no-lock"
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True
    message = str(exc_info.value)
    assert "simulation export" in message
    assert "simulation figures directory" in message


def test_run_simulation_accepts_expected_report_outputs(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    (tmp_path / "sim_workspace" / "exports" / "test_run").mkdir(parents=True)
    (tmp_path / "sim_workspace" / "exports" / "test_run" / "timeseries.csv").write_text(
        "datetime,value\n2020-01-01,1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "sim_workspace" / "figures" / "test_run").mkdir(parents=True)

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        lambda command, **kwargs: _CompletedRun(),
    )

    result = run_catchment_report_pipeline(
        config_path,
        run_simulation=True,
        build_context_artifacts=False,
        build_report_html=False,
    )

    assert result.simulation_config == tmp_path / "run_test.toml"
    assert result.context_summary is None
    assert result.html_report is None


def test_pipeline_toml_can_command_simulation_and_report_steps(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(
        config_path,
        pipeline="""
[pipeline]
run_simulation = true
build_context_artifacts = false
build_report_html = false
no_lock = false
""",
    )
    (tmp_path / "sim_workspace" / "exports" / "test_run").mkdir(parents=True)
    (tmp_path / "sim_workspace" / "exports" / "test_run" / "timeseries.csv").write_text(
        "datetime,value\n2020-01-01,1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "sim_workspace" / "figures" / "test_run").mkdir(parents=True)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _CompletedRun()

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        fake_run,
    )

    result = run_catchment_report_pipeline(config_path)

    assert result.simulation_config == tmp_path / "run_test.toml"
    assert result.context_summary is None
    assert result.html_report is None
    assert calls
    assert "--no-lock" not in calls[0][0]
    assert calls[0][1]["capture_output"] is True


def test_pipeline_can_stream_run_logs_from_toml(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(
        config_path,
        pipeline="""
[pipeline]
run_simulation = true
build_context_artifacts = false
build_report_html = false
stream_run_logs = true
""",
    )
    (tmp_path / "sim_workspace" / "exports" / "test_run").mkdir(parents=True)
    (tmp_path / "sim_workspace" / "exports" / "test_run" / "timeseries.csv").write_text(
        "datetime,value\n2020-01-01,1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "sim_workspace" / "figures" / "test_run").mkdir(parents=True)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return None

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        fake_run,
    )

    result = run_catchment_report_pipeline(config_path)

    assert result.simulation_config == tmp_path / "run_test.toml"
    assert calls
    assert calls[0][1]["check"] is True
    assert "capture_output" not in calls[0][1]
