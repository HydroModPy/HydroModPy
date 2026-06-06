from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.display.report_artifacts import REPORT_ARTIFACT_MANIFEST_SCHEMA
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.html_report import HtmlReportStep


def _ctx(report: object) -> SimpleNamespace:
    return SimpleNamespace(cfg=SimpleNamespace(report=report))


def _report(
    *,
    enabled: bool = True,
    build_at_end: bool = True,
    strict: bool = False,
    profile: str = "catchment_gauged",
    config_path: Path | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        html=SimpleNamespace(
            enabled=enabled,
            build_at_end=build_at_end,
            strict=strict,
            profile=profile,
            config_path=config_path,
        )
    )


def test_html_report_step_skips_when_build_at_end_false() -> None:
    state = PipelineState(
        run_id="r",
        data={"ctx": _ctx(_report(build_at_end=False))},
    )

    final = HtmlReportStep().run(state)

    assert final.get("html_report") is None
    assert final.get("html_report_postflight") is None
    assert final.get("html_report_error") is None


def test_html_report_step_records_non_strict_error() -> None:
    state = PipelineState(
        run_id="r",
        data={"ctx": _ctx(_report(config_path=None, strict=False))},
    )

    final = HtmlReportStep().run(state)

    assert final.get("html_report") is None
    assert final.get("html_report_error")
    assert "config_path" in final.get("html_report_error")


def test_html_report_step_raises_strict_error() -> None:
    state = PipelineState(
        run_id="r",
        data={"ctx": _ctx(_report(config_path=None, strict=True))},
    )

    with pytest.raises(ConfigError, match="config_path"):
        HtmlReportStep().run(state)


def test_html_report_step_runs_catchment_report_only(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    html_path = tmp_path / "report" / "web" / "index.html"
    postflight_path = tmp_path / "report" / "block_report_postflight.json"
    captured = {}

    def fake_pipeline(
        report_config: Path,
        *,
        run_overview: bool | None,
        run_simulation: bool | None,
        build_context_artifacts: bool | None,
        build_report_html: bool | None,
        strict_figure_postflight: bool | None,
        source_artifact_manifest: Path | None,
        simulation_config_path: Path | None,
    ):
        captured.update(
            report_config=report_config,
            run_overview=run_overview,
            run_simulation=run_simulation,
            build_context_artifacts=build_context_artifacts,
            build_report_html=build_report_html,
            strict_figure_postflight=strict_figure_postflight,
            source_artifact_manifest=source_artifact_manifest,
            simulation_config_path=simulation_config_path,
        )
        return SimpleNamespace(html_report=html_path, postflight_report=postflight_path)

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.run_catchment_report_pipeline",
        fake_pipeline,
    )
    state = PipelineState(
        run_id="r",
        data={"ctx": _ctx(_report(config_path=config_path, strict=False))},
    )

    final = HtmlReportStep().run(state)

    assert final.get("html_report") == html_path
    assert final.get("html_report_postflight") == postflight_path
    assert captured == {
        "report_config": config_path,
        "run_overview": False,
        "run_simulation": False,
        "build_context_artifacts": True,
        "build_report_html": True,
        "strict_figure_postflight": False,
        "source_artifact_manifest": None,
        "simulation_config_path": None,
    }


def test_html_report_step_passes_display_manifest_to_catchment_pipeline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    run_config_path = tmp_path / "run.toml"
    manifest_path = tmp_path / "figures" / "baseline" / "report_artifact_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": REPORT_ARTIFACT_MANIFEST_SCHEMA,
                "profile": "catchment_gauged",
                "summary": {"missing_required_count": 0},
                "artifacts": [
                    {
                        "artifact_id": "simulation.head.piezometric_map",
                        "required": True,
                        "status": "present",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_pipeline(
        report_config: Path,
        *,
        run_overview: bool | None,
        run_simulation: bool | None,
        build_context_artifacts: bool | None,
        build_report_html: bool | None,
        strict_figure_postflight: bool | None,
        source_artifact_manifest: Path | None,
        simulation_config_path: Path | None,
    ):
        captured.update(
            report_config=report_config,
            source_artifact_manifest=source_artifact_manifest,
            simulation_config_path=simulation_config_path,
        )
        del run_overview, run_simulation, build_context_artifacts, build_report_html
        del strict_figure_postflight
        return SimpleNamespace(
            html_report=tmp_path / "report" / "web" / "index.html",
            postflight_report=tmp_path / "report" / "block_report_postflight.json",
        )

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.run_catchment_report_pipeline",
        fake_pipeline,
    )
    ctx = _ctx(_report(config_path=config_path, strict=False))
    ctx.config_path = run_config_path
    state = PipelineState(
        run_id="r",
        data={"ctx": ctx, "report_display_manifest": manifest_path},
    )

    final = HtmlReportStep().run(state)

    assert final.get("html_report_source_manifest") == manifest_path
    assert captured["report_config"] == config_path
    assert captured["source_artifact_manifest"] == manifest_path
    assert captured["simulation_config_path"] == run_config_path


def test_html_report_step_rejects_missing_required_manifest_artifacts(tmp_path: Path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    manifest_path = tmp_path / "figures" / "baseline" / "report_artifact_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": REPORT_ARTIFACT_MANIFEST_SCHEMA,
                "profile": "catchment_gauged",
                "artifacts": [
                    {
                        "artifact_id": "simulation.head.piezometric_map",
                        "required": True,
                        "status": "missing",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state = PipelineState(
        run_id="r",
        data={
            "ctx": _ctx(_report(config_path=config_path, strict=True)),
            "report_display_manifest": manifest_path,
        },
    )

    with pytest.raises(ConfigError, match="missing required artifacts"):
        HtmlReportStep().run(state)
