from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import uuid
from pathlib import Path

import pytest

from hydromodpy.display.catchment_report import (
    GENERIC_REPORT_PRESET,
    CatchmentReportBuildOptions,
    CatchmentReportConfig,
    CatchmentReportInputs,
)
from hydromodpy.display.catchment_report.artifacts import DEFAULT_ARTIFACT_SPECS
from hydromodpy.display.catchment_report.block_specs import DEFAULT_BLOCK_SPECS
from hydromodpy.display.catchment_report.pipeline import CatchmentReportPipelineResult

REPO_ROOT = Path(__file__).resolve().parents[3]
NANCON_EXAMPLE_DIR = REPO_ROOT / "examples" / "projects" / "16_nancon_natural_calibration"
NANCON_REPORT_CONFIG = NANCON_EXAMPLE_DIR / "catchment_report.toml"
NANCON_HTML_REPORT_CONFIG = NANCON_EXAMPLE_DIR / "catchment_report_transient_nwt_html.toml"
NANCON_REPORT_INPUTS = CatchmentReportInputs.from_toml(NANCON_REPORT_CONFIG)
NANCON_HTML_REPORT_INPUTS = CatchmentReportInputs.from_toml(NANCON_HTML_REPORT_CONFIG)
PUBLIC_REPORT_CONFIGS = (
    NANCON_REPORT_CONFIG,
    NANCON_HTML_REPORT_CONFIG,
    REPO_ROOT / "examples" / "projects" / "06_vire_selune" / "catchment_report_selune.toml",
    REPO_ROOT / "examples" / "projects" / "06_vire_selune" / "catchment_report_vire.toml",
)
GITIGNORE = REPO_ROOT / ".gitignore"


def _load_nancon_report_module():
    module_path = NANCON_EXAMPLE_DIR / "nancon_real_figures_report.py"
    spec = importlib.util.spec_from_file_location(
        f"nancon_real_figures_report_{uuid.uuid4().hex}",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fingerprints(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.glob("*.png"))
    }


def _write_nancon_cli_report_config(
    config_path: Path,
    output_dir: Path,
    inputs: CatchmentReportInputs = NANCON_REPORT_INPUTS,
) -> None:
    config_path.write_text(
        "\n".join(
            [
                "[report]",
                f'site_label = "{inputs.site_label}"',
                f'station_label = "{inputs.station_label}"',
                f'output_dir = "{output_dir.as_posix()}"',
                "",
                "[layout]",
                f'watershed_project_dir = "{inputs.watershed_project_dir.as_posix()}"',
                f'context_outputs_dir = "{inputs.context_outputs_dir.as_posix()}"',
                f'data_overview_project_dir = "{inputs.data_overview_project_dir.as_posix()}"',
                f'simulation_workspace_dir = "{inputs.simulation_workspace_dir.as_posix()}"',
                f'simulation_name = "{inputs.simulation_name}"',
                f'context_summary_name = "{inputs.context_summary.name}"',
                f'transient_config_name = "{inputs.transient_config.name}"',
                f'overview_config_name = "{inputs.overview_config.name}"',
                "",
                "[context.observed_discharge]",
                f'path = "{inputs.observed_discharge_path.as_posix()}"',
                f'station_id = "{inputs.observed_discharge_station_id}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_nancon_example_report_config_uses_generic_contract() -> None:
    config = CatchmentReportConfig.from_inputs(NANCON_REPORT_INPUTS)

    assert NANCON_REPORT_INPUTS.output_dir == (
        REPO_ROOT
        / "examples"
        / "projects"
        / "16_nancon_natural_calibration"
        / "outputs"
        / "nancon_real_figures"
    )
    assert NANCON_REPORT_INPUTS.context_summary == (
        REPO_ROOT
        / "examples"
        / "projects"
        / "16_nancon_natural_calibration"
        / "outputs"
        / "nancon_context"
        / "context"
        / "nancon_catchment_context_summary.json"
    )
    assert NANCON_REPORT_INPUTS.preset_name is None
    assert config.preset is GENERIC_REPORT_PRESET
    assert config.artifact_specs is None
    assert config.block_specs is None
    assert NANCON_REPORT_INPUTS.observed_discharge_path == (
        REPO_ROOT
        / "examples"
        / "data"
        / "hydrometry"
        / "hydrometry_custom_NANCON_19820201_20220125_D.csv"
    )


@pytest.mark.parametrize("config_path", PUBLIC_REPORT_CONFIGS)
def test_public_catchment_report_configs_are_not_orchestrators(config_path: Path) -> None:
    text = config_path.read_text(encoding="utf-8")

    assert "[pipeline]" not in text
    options = CatchmentReportBuildOptions.from_toml(config_path)
    assert options.run_overview is False
    assert options.run_simulation is False


def test_generic_specs_do_not_include_gallery_or_nancon_specific_paths() -> None:
    candidates = [candidate for spec in DEFAULT_ARTIFACT_SPECS for candidate in spec.candidates]

    assert all(candidate.root != "gallery_geo" for candidate in candidates)
    assert all(candidate.root != "gallery_sim" for candidate in candidates)
    assert all("nancon" not in candidate.relative_path.lower() for candidate in candidates)


def test_generic_block_specs_do_not_carry_nancon_wording() -> None:
    generic_text = "\n".join(
        [
            *(spec.title for spec in DEFAULT_BLOCK_SPECS),
            *(spec.lead for spec in DEFAULT_BLOCK_SPECS),
            *(figure.title for spec in DEFAULT_BLOCK_SPECS for figure in spec.figures),
        ]
    ).lower()

    assert "nancon" not in generic_text
    assert "massif armoricain" not in generic_text
    assert "smoke" not in generic_text
    assert "future calibration" not in generic_text


def test_generated_report_artifacts_are_ignored_by_git() -> None:
    gitignore = GITIGNORE.read_text(encoding="utf-8")

    for pattern in (
        "examples/projects/**/outputs/**",
        "!examples/projects/**/outputs/.gitignore",
        "examples/projects/**/data/cache.duckdb*",
        "examples/projects/**/web/",
        "examples/projects/**/web_review/",
        "examples/data/etp/etp_sim2_*.nc",
        "examples/data/recharge/recharge_sim2_*.nc",
        "examples/projects/**/hydromodpy.lock",
    ):
        assert pattern in gitignore


def test_generated_report_ignore_policy_is_not_basin_specific() -> None:
    gitignore = GITIGNORE.read_text(encoding="utf-8")

    basin_specific_patterns = (
        "examples/projects/06_vire_selune/outputs/",
        "examples/projects/16_nancon_natural_calibration/outputs/nancon_context/",
        "examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/",
        "examples/projects/16_nancon_natural_calibration/outputs/selune_portability_probe/",
    )

    assert all(pattern not in gitignore for pattern in basin_specific_patterns)


def test_nancon_inputs_can_be_derived_from_project_layout() -> None:
    derived = CatchmentReportInputs.from_project_layout(
        output_dir=NANCON_REPORT_INPUTS.output_dir,
        site_label=NANCON_REPORT_INPUTS.site_label,
        station_label=NANCON_REPORT_INPUTS.station_label,
        watershed_project_dir=REPO_ROOT / "examples" / "projects" / "02_nancon_watershed",
        context_outputs_dir=REPO_ROOT
        / "examples"
        / "projects"
        / "16_nancon_natural_calibration"
        / "outputs"
        / "nancon_context",
        data_overview_project_dir=REPO_ROOT / "examples" / "projects" / "02_nancon_watershed",
        simulation_workspace_dir=REPO_ROOT / "examples" / "projects" / "02_nancon_watershed",
        simulation_name="transient_nwt",
        context_summary_name="nancon_catchment_context_summary.json",
        overview_config_name="run_overview_all_apis.toml",
        observed_discharge_path=REPO_ROOT
        / "examples"
        / "data"
        / "hydrometry"
        / "hydrometry_custom_NANCON_19820201_20220125_D.csv",
        observed_discharge_station_id="NANCON",
    )

    assert derived == NANCON_REPORT_INPUTS


def test_nancon_inputs_can_be_loaded_from_report_toml() -> None:
    assert CatchmentReportInputs.from_toml(NANCON_REPORT_CONFIG) == NANCON_REPORT_INPUTS


def test_nancon_report_code_calls_catchment_pipeline_directly(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    module = _load_nancon_report_module()
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

    monkeypatch.setattr(module, "run_catchment_report_pipeline", fake_pipeline)

    result = module.build_nancon_real_figures_report(
        run_overview=False,
        run_simulation=False,
        build_report_html=True,
    )

    assert result.html_report == tmp_path / "web" / "index.html"
    assert captured["report_config"] == NANCON_REPORT_CONFIG
    assert captured["preset"] is None
    assert captured["run_overview"] is False
    assert captured["run_simulation"] is False
    assert captured["build_report_html"] is True

    captured.clear()
    assert module.main(["--report-only"]) == 0

    assert captured["report_config"] == NANCON_REPORT_CONFIG
    assert captured["run_overview"] is False
    assert captured["run_simulation"] is False
    assert captured["build_context_artifacts"] is False
    assert captured["build_report_html"] is True
    assert f"html_report={tmp_path / 'web' / 'index.html'}" in capsys.readouterr().out


def test_nancon_report_launcher_does_not_call_global_hmp_cli() -> None:
    launcher = (NANCON_EXAMPLE_DIR / "build_nancon_real_figures_report.py").read_text(
        encoding="utf-8"
    )

    assert "hydromodpy.cli.main" not in launcher
    assert "hmp_main" not in launcher


def test_generic_inputs_support_separate_simulation_workspace_and_observed_series() -> None:
    config_path = (
        REPO_ROOT / "examples" / "projects" / "06_vire_selune" / "catchment_report_selune.toml"
    )
    inputs = CatchmentReportInputs.from_toml(config_path)
    options = CatchmentReportBuildOptions.from_toml(config_path)
    config = CatchmentReportConfig.from_inputs(inputs)

    assert inputs.site_label == "Selune"
    assert inputs.watershed_project_dir == REPO_ROOT / "examples" / "projects" / "06_vire_selune"
    assert (
        inputs.simulation_workspace_dir == inputs.watershed_project_dir / "outputs" / "selune_nwt"
    )
    assert inputs.simulation_figures == (
        inputs.simulation_workspace_dir / "figures" / "selune_nwt_report"
    )
    assert inputs.simulation_export == (
        inputs.simulation_workspace_dir / "exports" / "selune_nwt_report" / "timeseries.csv"
    )
    assert inputs.observed_discharge_station_id == "I922102001"
    assert inputs.preset_name is None
    assert options.run_overview is False
    assert options.run_simulation is False
    assert options.build_context_artifacts is True
    assert options.build_report_html is True
    assert options.strict_figure_postflight is False
    assert inputs.observed_discharge_path == (
        REPO_ROOT
        / "examples"
        / "data"
        / "hydrometry"
        / "hydrometry_hubeau_I922102001_20200101_20201231_D.csv"
    )
    assert config.preset is GENERIC_REPORT_PRESET


@pytest.mark.regression
def test_report_catchment_cli_regenerates_existing_nancon_report(
    tmp_path,
) -> None:
    from hydromodpy.cli.main import main as hmp_cli_main

    reference = NANCON_HTML_REPORT_INPUTS.output_dir
    required_reference_files = (
        reference / "web" / "index.html",
        reference / "web_review" / "compact" / "index.html",
        reference / "web_review" / "standard" / "index.html",
        reference / "web_review" / "audit" / "index.html",
        reference / "web_review" / "by_block" / "index.html",
    )
    if not all(path.exists() for path in required_reference_files):
        pytest.skip("Local Nancon HTML outputs are not available.")
    if not (reference / "web" / "figures").exists():
        pytest.skip("Local Nancon report figures are not available.")
    if not NANCON_REPORT_INPUTS.context_summary.exists():
        pytest.skip("Local Nancon generic context summary is not available.")

    generated = reference.parent / f"_nancon_regen_test_{uuid.uuid4().hex}"
    shutil.rmtree(generated, ignore_errors=True)
    try:
        config_path = tmp_path / "catchment_report.toml"
        _write_nancon_cli_report_config(config_path, generated, NANCON_HTML_REPORT_INPUTS)
        hmp_cli_main(
            [
                "report",
                "catchment",
                str(config_path),
                "--report-only",
            ]
        )

        for reference_html in required_reference_files:
            generated_html = generated / reference_html.relative_to(reference)
            text = generated_html.read_text(encoding="utf-8")
            assert text.startswith("<!doctype html>")
            assert "Nancon" in text

        generated_figures = _fingerprints(generated / "web" / "figures")
        assert set(generated_figures) == set(_fingerprints(reference / "web" / "figures"))
        assert all(size > 0 for size, _digest in generated_figures.values())
        postflight = json.loads((generated / "block_report_postflight.json").read_text())
        assert postflight["missing_count"] == 0
        assert postflight["dangling_count"] == 0
        artifact_manifest = json.loads((generated / "report_artifact_manifest.json").read_text())
        assert all(
            artifact["status"] == "present"
            for artifact in artifact_manifest["artifacts"]
            if artifact["required"]
        )
    finally:
        shutil.rmtree(generated, ignore_errors=True)
