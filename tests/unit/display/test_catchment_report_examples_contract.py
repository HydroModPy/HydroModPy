from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import runs_dir_for
from hydromodpy.display.catchment_report import (
    GENERIC_REPORT_PRESET,
    CatchmentReportConfig,
    CatchmentReportInputs,
)
from hydromodpy.display.catchment_report.artifacts import DEFAULT_ARTIFACT_SPECS
from hydromodpy.display.catchment_report.block_specs import DEFAULT_BLOCK_SPECS
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME

REPO_ROOT = Path(__file__).resolve().parents[3]
NANCON_EXAMPLE_DIR = REPO_ROOT / "examples" / "projects" / "16_nancon_natural_calibration"
NANCON_REPORT_CONFIG = NANCON_EXAMPLE_DIR / "catchment_report.toml"
NANCON_REPORT_INPUTS = CatchmentReportInputs.from_toml(NANCON_REPORT_CONFIG)
GITIGNORE = REPO_ROOT / ".gitignore"


def _fingerprints(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.glob("*.png"))
    }


def _write_nancon_cli_report_config(config_path: Path, output_dir: Path) -> None:
    inputs = NANCON_REPORT_INPUTS
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
                "[pipeline]",
                f"run_overview = {str(inputs.pipeline_run_overview).lower()}",
                f"run_simulation = {str(inputs.pipeline_run_simulation).lower()}",
                f"build_context_artifacts = {str(inputs.pipeline_build_context_artifacts).lower()}",
                f"build_report_html = {str(inputs.pipeline_build_report_html).lower()}",
                f"strict_figure_postflight = {str(inputs.pipeline_strict_figure_postflight).lower()}",
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


def test_generic_specs_do_not_include_gallery_or_nancon_fallbacks() -> None:
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

    legacy_patterns = (
        "examples/projects/06_vire_selune/outputs/",
        "examples/projects/16_nancon_natural_calibration/outputs/nancon_context/",
        "examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/",
        "examples/projects/16_nancon_natural_calibration/outputs/selune_portability_probe/",
    )

    assert all(pattern not in gitignore for pattern in legacy_patterns)


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
        pipeline_run_overview=True,
        pipeline_run_simulation=True,
        pipeline_build_context_artifacts=True,
        pipeline_build_report_html=True,
        pipeline_strict_figure_postflight=True,
    )

    assert derived == NANCON_REPORT_INPUTS


def test_nancon_inputs_can_be_loaded_from_report_toml() -> None:
    assert CatchmentReportInputs.from_toml(NANCON_REPORT_CONFIG) == NANCON_REPORT_INPUTS


def test_generic_inputs_support_separate_simulation_workspace_and_observed_series() -> None:
    config_path = (
        REPO_ROOT / "examples" / "projects" / "06_vire_selune" / "catchment_report_selune.toml"
    )
    inputs = CatchmentReportInputs.from_toml(config_path)
    config = CatchmentReportConfig.from_inputs(inputs)

    assert inputs.site_label == "Selune"
    assert inputs.watershed_project_dir == REPO_ROOT / "examples" / "projects" / "06_vire_selune"
    assert (
        inputs.simulation_workspace_dir == inputs.watershed_project_dir / "outputs" / "selune_nwt"
    )
    assert inputs.simulation_figures == (
        runs_dir_for(inputs.simulation_workspace_dir) / "selune_nwt_report" / RUN_FIGURES_DIRNAME
    )
    assert not hasattr(inputs, "simulation_export")
    assert inputs.observed_discharge_station_id == "I922102001"
    assert inputs.preset_name is None
    assert inputs.pipeline_run_overview is True
    assert inputs.pipeline_run_simulation is True
    assert inputs.pipeline_build_context_artifacts is True
    assert inputs.pipeline_build_report_html is True
    assert inputs.pipeline_strict_figure_postflight is True
    assert inputs.observed_discharge_path == (
        REPO_ROOT
        / "examples"
        / "data"
        / "hydrometry"
        / "hydrometry_hubeau_I922102001_20200101_20201231_D.csv"
    )
    assert config.preset is GENERIC_REPORT_PRESET


def _write_synthetic_report_config(config_path: Path, root: Path, output_dir: Path) -> None:
    """Lay out the smallest project the report pipeline accepts, on tmp_path.

    The real Nancon inputs live under ``examples/**/outputs/``, which
    ``.gitignore`` excludes, so a test that reads them can only ever skip.
    Everything the builder needs is either a directory it globs for figures
    (empty is legal) or one small JSON, so the whole thing fits in tmp_path.
    """
    watershed = root / "watershed"
    context = root / "context"
    data_overview = root / "data_overview"
    simulation = root / "sim_workspace"
    for directory in (watershed, data_overview, simulation):
        directory.mkdir(parents=True, exist_ok=True)
    (context / "context").mkdir(parents=True, exist_ok=True)
    (context / "web" / "assets").mkdir(parents=True, exist_ok=True)
    (context / "context" / "site_gauged_context_summary.json").write_text(
        json.dumps({"configuration": {"site": "synthetic", "epsg": 2154}}),
        encoding="utf-8",
    )
    # CatchmentReportInputs resolves these two against watershed_project_dir
    # and data_overview_project_dir, not against the simulation workspace.
    (watershed / "transient.toml").write_text('[simulation]\nname = "t"\n', encoding="utf-8")
    (data_overview / "overview.toml").write_text('[simulation]\nname = "o"\n', encoding="utf-8")

    config_path.write_text(
        "\n".join(
            [
                "[report]",
                'site_label = "synthetic"',
                'station_label = "S1"',
                f'output_dir = "{output_dir.as_posix()}"',
                "",
                "[layout]",
                f'watershed_project_dir = "{watershed.as_posix()}"',
                f'context_outputs_dir = "{context.as_posix()}"',
                f'data_overview_project_dir = "{data_overview.as_posix()}"',
                f'simulation_workspace_dir = "{simulation.as_posix()}"',
                'simulation_name = "t"',
                'context_summary_name = "site_gauged_context_summary.json"',
                'transient_config_name = "transient.toml"',
                'overview_config_name = "overview.toml"',
                "",
            ]
        ),
        encoding="utf-8",
    )


REPORT_PAGES = (
    Path("web") / "index.html",
    Path("web_review") / "compact" / "index.html",
    Path("web_review") / "standard" / "index.html",
    Path("web_review") / "audit" / "index.html",
    Path("web_review") / "by_block" / "index.html",
)


def test_report_catchment_cli_builds_every_page(tmp_path) -> None:
    """`hmp report catchment --report-only` emits the five documented pages.

    This is the only test in the suite that reaches ``build_catchment_report``
    without a monkeypatch: every other report test stubs the builder out.
    """
    from hydromodpy.cli.main import main as hmp_cli_main

    output_dir = tmp_path / "report"
    config_path = tmp_path / "catchment_report.toml"
    _write_synthetic_report_config(config_path, tmp_path / "project", output_dir)

    hmp_cli_main(["report", "catchment", str(config_path), "--report-only"])

    for page in REPORT_PAGES:
        rendered = output_dir / page
        assert rendered.is_file(), f"missing report page: {page}"
        assert "<html" in rendered.read_text(encoding="utf-8").lower()


def test_report_catchment_cli_regeneration_is_byte_identical(tmp_path) -> None:
    """Regenerating from unchanged inputs must not perturb a single byte.

    A timestamp, a dict iteration order or an unseeded colour ramp leaking into
    the HTML would show up here as a diff. This used to be checked against a
    developer's local Nancon outputs, so it never ran anywhere.
    """
    from hydromodpy.cli.main import main as hmp_cli_main

    config_path = tmp_path / "catchment_report.toml"
    first = tmp_path / "first"
    second = tmp_path / "second"

    _write_synthetic_report_config(config_path, tmp_path / "project", first)
    hmp_cli_main(["report", "catchment", str(config_path), "--report-only"])

    _write_synthetic_report_config(config_path, tmp_path / "project", second)
    hmp_cli_main(["report", "catchment", str(config_path), "--report-only"])

    for page in REPORT_PAGES:
        assert (second / page).read_text(encoding="utf-8") == (first / page).read_text(
            encoding="utf-8"
        ), f"non-deterministic report page: {page}"

    assert _fingerprints(second / "web" / "figures") == _fingerprints(first / "web" / "figures")
