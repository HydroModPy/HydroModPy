from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.display.catchment_report import pipeline as pipeline_module
from hydromodpy.display.catchment_report.pipeline import (
    CatchmentReportPipelineResult,
    run_catchment_report_pipeline,
)
from hydromodpy.display.catchment_report.preflight import CatchmentReportPreflightError
from hydromodpy.display.report_artifacts import REPORT_ARTIFACT_MANIFEST_SCHEMA


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


def _write_transient_config(root: Path) -> None:
    (root / "run_test.toml").write_text("[simulation]\n", encoding="utf-8")


def _write_overview_config(root: Path) -> None:
    (root / "config_overview.toml").write_text("[overview]\n", encoding="utf-8")


def test_run_simulation_validates_expected_report_outputs(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
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
    assert calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["errors"] == "replace"
    assert calls[0][1]["text"] is True
    message = str(exc_info.value)
    assert "simulation export" in message
    assert "simulation figures directory" in message


def test_run_simulation_accepts_expected_report_outputs(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
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
    _write_transient_config(tmp_path)
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
    _write_transient_config(tmp_path)
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


def test_pipeline_runs_overview_before_simulation_from_toml(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(
        config_path,
        pipeline="""
[pipeline]
run_overview = true
run_simulation = true
build_context_artifacts = false
build_report_html = false
""",
    )
    _write_overview_config(tmp_path)
    _write_transient_config(tmp_path)
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

    assert result.overview_config == tmp_path / "config_overview.toml"
    assert result.simulation_config == tmp_path / "run_test.toml"
    assert [Path(command[4]) for command, _kwargs in calls] == [
        tmp_path / "config_overview.toml",
        tmp_path / "run_test.toml",
    ]


def test_preflight_reports_missing_simulation_config_before_run(
    monkeypatch,
    tmp_path,
) -> None:
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

    with pytest.raises(CatchmentReportPreflightError) as exc_info:
        run_catchment_report_pipeline(
            config_path,
            run_simulation=True,
            build_context_artifacts=False,
            build_report_html=False,
        )

    assert calls == []
    assert "simulation config" in str(exc_info.value)


def test_preflight_reports_missing_context_for_report_only(tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    (tmp_path / "figures" / "overview").mkdir(parents=True)
    (tmp_path / "sim_workspace" / "figures" / "test_run").mkdir(parents=True)

    with pytest.raises(CatchmentReportPreflightError) as exc_info:
        run_catchment_report_pipeline(
            config_path,
            run_simulation=False,
            build_context_artifacts=False,
            build_report_html=True,
        )

    message = str(exc_info.value)
    assert "context summary" in message


def test_missing_optional_observed_discharge_does_not_block_context_build(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    config_path.write_text(
        """
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

[context.observed_discharge]
path = "missing_observed.csv"
""".lstrip(),
        encoding="utf-8",
    )
    _write_transient_config(tmp_path)
    (tmp_path / "sim_workspace" / "exports" / "test_run").mkdir(parents=True)
    (tmp_path / "sim_workspace" / "exports" / "test_run" / "timeseries.csv").write_text(
        "datetime,value\n2020-01-01,1.0\n",
        encoding="utf-8",
    )
    context_summary = tmp_path / "context" / "context" / "summary.json"

    def fake_build_context(inputs):
        context_summary.parent.mkdir(parents=True)
        context_summary.write_text("{}\n", encoding="utf-8")
        return context_summary

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.build_context",
        fake_build_context,
    )

    result = run_catchment_report_pipeline(
        config_path,
        run_simulation=False,
        build_context_artifacts=True,
        build_report_html=False,
    )

    assert result.context_summary == context_summary


def test_pipeline_writes_postflight_report_after_html(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    (tmp_path / "context" / "context").mkdir(parents=True)
    (tmp_path / "context" / "context" / "test_gauged_context_summary.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (tmp_path / "context" / "web" / "assets").mkdir(parents=True)
    (tmp_path / "figures" / "overview").mkdir(parents=True)
    (tmp_path / "sim_workspace" / "figures" / "test_run").mkdir(parents=True)
    html_path = tmp_path / "report" / "web" / "index.html"
    postflight_path = tmp_path / "report" / "block_report_postflight.json"
    captured = {}

    def fake_build(config):
        captured["build_config"] = config
        html_path.parent.mkdir(parents=True)
        html_path.write_text("<html></html>\n", encoding="utf-8")
        return html_path

    def fake_postflight(config, *, strict: bool):
        captured["postflight_config"] = config
        captured["strict"] = strict
        postflight_path.parent.mkdir(parents=True, exist_ok=True)
        postflight_path.write_text("{}\n", encoding="utf-8")
        return postflight_path

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.build_catchment_report",
        fake_build,
    )
    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.write_figure_postflight_report",
        fake_postflight,
    )

    result = run_catchment_report_pipeline(
        config_path,
        run_simulation=False,
        build_context_artifacts=False,
        build_report_html=True,
        strict_figure_postflight=True,
    )

    assert result.html_report == html_path
    assert result.postflight_report == postflight_path
    assert captured["postflight_config"] is captured["build_config"]
    assert captured["strict"] is True


def test_pipeline_source_manifest_overrides_simulation_artifact_inputs(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    source_manifest = (
        tmp_path / "workspace" / "figures" / "manifest_run" / "report_artifact_manifest.json"
    )
    source_manifest.parent.mkdir(parents=True)
    source_manifest.write_text(
        json.dumps(
            {
                "schema_version": REPORT_ARTIFACT_MANIFEST_SCHEMA,
                "profile": "catchment_gauged",
                "metadata": {"simulation_name": "manifest_run"},
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    run_config = tmp_path / "workspace" / "run_manifest.toml"
    run_config.parent.mkdir(parents=True, exist_ok=True)
    run_config.write_text("[simulation]\n", encoding="utf-8")
    (tmp_path / "workspace" / "exports" / "manifest_run").mkdir(parents=True)
    (tmp_path / "workspace" / "exports" / "manifest_run" / "timeseries.csv").write_text(
        "datetime,value\n2020-01-01,1.0\n",
        encoding="utf-8",
    )
    overview_manifest = tmp_path / "figures" / "overview" / "report_artifact_manifest.json"
    overview_manifest.parent.mkdir(parents=True, exist_ok=True)
    overview_manifest.write_text(
        json.dumps(
            {
                "schema_version": REPORT_ARTIFACT_MANIFEST_SCHEMA,
                "profile": "catchment_gauged",
                "metadata": {"artifact_scope": "data_overview.display"},
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_build_context(inputs):
        captured["context_inputs"] = inputs
        inputs.context_summary.parent.mkdir(parents=True, exist_ok=True)
        inputs.context_summary.write_text("{}\n", encoding="utf-8")
        context_manifest = inputs.context_outputs_dir / "report_artifact_manifest.json"
        context_manifest.parent.mkdir(parents=True, exist_ok=True)
        context_manifest.write_text(
            json.dumps(
                {
                    "schema_version": REPORT_ARTIFACT_MANIFEST_SCHEMA,
                    "profile": "catchment_gauged",
                    "metadata": {"artifact_scope": "catchment.context"},
                    "artifacts": [],
                }
            ),
            encoding="utf-8",
        )
        return inputs.context_summary

    def fake_build(config):
        captured["report_config"] = config
        html_path = config.output_dir / "web" / "index.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>\n", encoding="utf-8")
        return html_path

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.build_context",
        fake_build_context,
    )
    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.build_catchment_report",
        fake_build,
    )
    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.write_figure_postflight_report",
        lambda config, *, strict: config.output_dir / "block_report_postflight.json",
    )

    result = run_catchment_report_pipeline(
        config_path,
        run_simulation=False,
        build_context_artifacts=True,
        build_report_html=True,
        source_artifact_manifest=source_manifest,
        simulation_config_path=run_config,
    )
    context_manifest = tmp_path / "context" / "report_artifact_manifest.json"

    context_inputs = captured["context_inputs"]
    assert context_inputs.simulation_name == "manifest_run"
    assert context_inputs.simulation_figures == source_manifest.parent
    assert context_inputs.simulation_export == (
        tmp_path / "workspace" / "exports" / "manifest_run" / "timeseries.csv"
    )
    assert context_inputs.transient_config == run_config.resolve()
    assert captured["report_config"].upstream_artifact_manifest == source_manifest
    assert captured["report_config"].upstream_artifact_manifests == (
        source_manifest,
        overview_manifest,
        context_manifest,
    )
    assert result.context_artifact_manifest == context_manifest
    assert result.overview_artifact_manifest == overview_manifest


def test_pipeline_main_uses_shared_report_only_arguments(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    captured = {}

    def fake_pipeline(
        report_config: Path,
        *,
        preset,
        run_overview: bool | None,
        run_simulation: bool | None,
        build_context_artifacts: bool | None,
        build_report_html: bool | None,
        no_lock: bool | None,
        stream_run_logs: bool | None,
        strict_figure_postflight: bool | None,
    ) -> CatchmentReportPipelineResult:
        captured.update(
            report_config=report_config,
            preset=preset,
            run_overview=run_overview,
            run_simulation=run_simulation,
            build_context_artifacts=build_context_artifacts,
            build_report_html=build_report_html,
            no_lock=no_lock,
            stream_run_logs=stream_run_logs,
            strict_figure_postflight=strict_figure_postflight,
        )
        return CatchmentReportPipelineResult(
            overview_config=None,
            simulation_config=None,
            context_summary=None,
            html_report=tmp_path / "web" / "index.html",
        )

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.run_catchment_report_pipeline",
        fake_pipeline,
    )

    result = pipeline_module.main(
        [
            "--report-config",
            str(config_path),
            "--report-only",
        ]
    )

    assert result == 0
    assert captured["report_config"] == config_path
    assert captured["run_overview"] is False
    assert captured["run_simulation"] is False
    assert captured["build_context_artifacts"] is False
    assert captured["build_report_html"] is True
    assert f"html_report={tmp_path / 'web' / 'index.html'}" in capsys.readouterr().out


@pytest.mark.parametrize("removed_flag", ["--no-context", "--no-report"])
def test_pipeline_main_rejects_removed_skip_aliases(
    capsys,
    removed_flag: str,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"

    with pytest.raises(SystemExit):
        pipeline_module.main(["--report-config", str(config_path), removed_flag])

    assert f"unrecognized arguments: {removed_flag}" in capsys.readouterr().err
