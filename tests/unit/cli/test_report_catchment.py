"""Tests for the ``hmp report catchment`` command wiring."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG
from hydromodpy.display.catchment_report.pipeline import CatchmentReportPipelineResult
from hydromodpy.display.catchment_report.presets import CatchmentReportPreset


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def test_report_catchment_dispatches_to_pipeline(monkeypatch, capsys, tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    captured = {}

    def fake_pipeline(
        report_config: Path,
        *,
        preset: CatchmentReportPreset | None,
        run_overview: bool,
        run_simulation: bool,
        build_context_artifacts: bool,
        build_report_html: bool,
        no_lock: bool,
    ) -> CatchmentReportPipelineResult:
        captured.update(
            report_config=report_config,
            preset=preset,
            run_overview=run_overview,
            run_simulation=run_simulation,
            build_context_artifacts=build_context_artifacts,
            build_report_html=build_report_html,
            no_lock=no_lock,
        )
        return CatchmentReportPipelineResult(
            overview_config=None,
            simulation_config=None,
            context_summary=tmp_path / "context_summary.json",
            html_report=tmp_path / "web" / "index.html",
        )

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.run_catchment_report_pipeline",
        fake_pipeline,
    )

    _load_main().main(["report", "catchment", str(config_path)])

    assert captured == {
        "report_config": config_path,
        "preset": None,
        "run_overview": False,
        "run_simulation": False,
        "build_context_artifacts": True,
        "build_report_html": True,
        "no_lock": True,
    }
    out = capsys.readouterr().out
    assert f"context_summary={tmp_path / 'context_summary.json'}" in out
    assert f"html_report={tmp_path / 'web' / 'index.html'}" in out


def test_report_catchment_flags_control_pipeline(monkeypatch, capsys, tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    captured = {}

    def fake_pipeline(
        report_config: Path,
        *,
        preset: CatchmentReportPreset | None,
        run_overview: bool,
        run_simulation: bool,
        build_context_artifacts: bool,
        build_report_html: bool,
        no_lock: bool,
    ) -> CatchmentReportPipelineResult:
        captured.update(
            report_config=report_config,
            preset=preset,
            run_overview=run_overview,
            run_simulation=run_simulation,
            build_context_artifacts=build_context_artifacts,
            build_report_html=build_report_html,
            no_lock=no_lock,
        )
        return CatchmentReportPipelineResult(
            overview_config=tmp_path / "overview.toml",
            simulation_config=tmp_path / "simulation.toml",
            context_summary=tmp_path / "context_summary.json",
            html_report=None,
        )

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.run_catchment_report_pipeline",
        fake_pipeline,
    )

    _load_main().main(
        [
            "report",
            "catchment",
            str(config_path),
            "--run-overview",
            "--run-simulation",
            "--context-only",
            "--with-lock",
        ]
    )

    assert captured == {
        "report_config": config_path,
        "preset": None,
        "run_overview": True,
        "run_simulation": True,
        "build_context_artifacts": True,
        "build_report_html": False,
        "no_lock": False,
    }
    out = capsys.readouterr().out
    assert f"overview_config={tmp_path / 'overview.toml'}" in out
    assert f"simulation_config={tmp_path / 'simulation.toml'}" in out
    assert f"context_summary={tmp_path / 'context_summary.json'}" in out
    assert "html_report=" not in out


def test_report_catchment_rejects_context_only_with_report_only(capsys, tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"

    with pytest.raises(SystemExit) as exc_info:
        _load_main().main(
            [
                "report",
                "catchment",
                str(config_path),
                "--context-only",
                "--report-only",
            ]
        )

    assert exc_info.value.code == EXIT_CONFIG
    assert "mutually exclusive" in capsys.readouterr().err
