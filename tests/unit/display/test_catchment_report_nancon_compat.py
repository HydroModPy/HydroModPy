from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

import pytest

from hydromodpy.display.catchment_report import (
    GENERIC_REPORT_PRESET,
    NANCON_REPORT_CONFIG,
    NANCON_REPORT_PRESET,
    CatchmentReportConfig,
    CatchmentReportInputs,
    nancon_compat,
)
from hydromodpy.display.catchment_report.artifacts import NANCON_ARTIFACT_SPECS
from hydromodpy.display.catchment_report.block_specs import NANCON_BLOCK_SPECS
from hydromodpy.display.catchment_report.paths import NANCON_REPORT_INPUTS

REPO_ROOT = Path(__file__).resolve().parents[3]


def _fingerprints(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.glob("*.png"))
    }


def test_nancon_compat_keeps_reference_default_paths() -> None:
    assert nancon_compat.DEFAULT_OUTPUT_DIR == NANCON_REPORT_INPUTS.output_dir
    assert nancon_compat.CONTEXT_SUMMARY == NANCON_REPORT_INPUTS.context_summary
    assert nancon_compat.DEFAULT_REPORT_CONFIG == NANCON_REPORT_CONFIG
    assert nancon_compat.DEFAULT_OUTPUT_DIR == (
        REPO_ROOT
        / "examples"
        / "projects"
        / "16_nancon_natural_calibration"
        / "outputs"
        / "nancon_real_figures"
    )
    assert nancon_compat.CONTEXT_SUMMARY == (
        REPO_ROOT
        / "examples"
        / "projects"
        / "15_nancon_gauged_context"
        / "outputs"
        / "context"
        / "nancon_gauged_context_summary.json"
    )


def test_nancon_preset_groups_reference_specs() -> None:
    assert NANCON_REPORT_PRESET.name == "nancon_reference"
    assert NANCON_REPORT_PRESET.artifact_specs is NANCON_ARTIFACT_SPECS
    assert NANCON_REPORT_PRESET.block_specs is NANCON_BLOCK_SPECS
    assert NANCON_REPORT_PRESET.allow_gallery_fallbacks is True


def test_nancon_inputs_build_reference_config() -> None:
    config = CatchmentReportConfig.from_inputs(
        NANCON_REPORT_INPUTS,
        preset=NANCON_REPORT_PRESET,
    )

    assert config.output_dir == NANCON_REPORT_INPUTS.output_dir
    assert config.site_label == "Nancon"
    assert config.station_label == "Nancon a Lecousse"
    assert config.preset is NANCON_REPORT_PRESET
    assert config.artifact_specs is None
    assert config.block_specs is None
    assert config.allow_gallery_fallbacks is False


def test_nancon_inputs_can_be_derived_from_project_layout() -> None:
    derived = CatchmentReportInputs.from_project_layout(
        output_dir=NANCON_REPORT_INPUTS.output_dir,
        site_label=NANCON_REPORT_INPUTS.site_label,
        station_label=NANCON_REPORT_INPUTS.station_label,
        watershed_project_dir=REPO_ROOT / "examples" / "projects" / "02_nancon_watershed",
        context_outputs_dir=REPO_ROOT
        / "examples"
        / "projects"
        / "15_nancon_gauged_context"
        / "outputs",
        simulation_name="transient_nwt",
        context_summary_name="nancon_gauged_context_summary.json",
        allow_gallery_fallbacks=False,
    )

    assert derived == NANCON_REPORT_INPUTS


def test_nancon_inputs_can_be_loaded_from_report_toml() -> None:
    assert CatchmentReportInputs.from_toml(NANCON_REPORT_CONFIG) == NANCON_REPORT_INPUTS


def test_generic_inputs_support_separate_simulation_workspace_and_observed_series() -> None:
    config_path = (
        REPO_ROOT
        / "examples"
        / "projects"
        / "06_vire_selune"
        / "catchment_report_selune.toml"
    )
    inputs = CatchmentReportInputs.from_toml(config_path)
    config = CatchmentReportConfig.from_inputs(inputs)

    assert inputs.site_label == "Selune"
    assert inputs.watershed_project_dir == REPO_ROOT / "examples" / "projects" / "06_vire_selune"
    assert inputs.simulation_workspace_dir == inputs.watershed_project_dir / "outputs" / "selune_nwt"
    assert inputs.simulation_figures == (
        inputs.simulation_workspace_dir / "figures" / "selune_nwt_report"
    )
    assert inputs.simulation_export == (
        inputs.simulation_workspace_dir / "exports" / "selune_nwt_report" / "timeseries.csv"
    )
    assert inputs.observed_discharge_station_id == "I922102001"
    assert inputs.observed_discharge_path == (
        REPO_ROOT
        / "examples"
        / "data"
        / "hydrometry"
        / "hydrometry_hubeau_I922102001_20200101_20201231_D.csv"
    )
    assert config.preset is GENERIC_REPORT_PRESET
    assert config.allow_gallery_fallbacks is False


@pytest.mark.regression
def test_nancon_compat_regenerates_existing_reference_report() -> None:
    reference = nancon_compat.DEFAULT_OUTPUT_DIR
    required_reference_files = (
        reference / "web" / "index.html",
        reference / "web_review" / "compact" / "index.html",
        reference / "web_review" / "standard" / "index.html",
        reference / "web_review" / "audit" / "index.html",
        reference / "web_review" / "by_block" / "index.html",
    )
    if not all(path.exists() for path in required_reference_files):
        pytest.skip("Local Nancon reference HTML outputs are not available.")
    if not (reference / "web" / "figures").exists():
        pytest.skip("Local Nancon reference figures are not available.")

    generated = reference.parent / f"_nancon_regen_test_{uuid.uuid4().hex}"
    shutil.rmtree(generated, ignore_errors=True)
    try:
        assert nancon_compat.main(["--output-dir", str(generated)]) == 0

        for reference_html in required_reference_files:
            generated_html = generated / reference_html.relative_to(reference)
            assert generated_html.read_text(encoding="utf-8") == reference_html.read_text(
                encoding="utf-8"
            )

        assert _fingerprints(generated / "web" / "figures") == _fingerprints(
            reference / "web" / "figures"
        )
    finally:
        shutil.rmtree(generated, ignore_errors=True)
