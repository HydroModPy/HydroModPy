from __future__ import annotations

from pathlib import Path
import sys

from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.analysis.comparison.config import MethodComparisonConfig
from examples.projects.launcher_simulation.realistic_campaign.run_campaign import (
    CampaignExecution,
    build_execution_report,
    build_run_command,
    filter_campaign_cases,
    load_campaign_manifest,
)


def _write_campaign_manifest(tmp_path: Path) -> Path:
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    (configs_dir / "sim.toml").write_text("[simulation]\nrun_id = \"demo\"\n", encoding="utf-8")
    (configs_dir / "compare.toml").write_text("[method_comparison]\ncomparison_id = \"demo\"\n", encoding="utf-8")

    manifest_path = tmp_path / "campaign.toml"
    manifest_path.write_text(
        "\n".join(
            [
                "[campaign]",
                'campaign_id = "demo_campaign"',
                'label = "Demo campaign"',
                'output_root = "./outputs"',
                "continue_on_error = false",
                "",
                "[[campaign.case]]",
                'id = "demo_sim"',
                'launcher = "simulation"',
                'config = "configs/sim.toml"',
                'tier = "smoke"',
                'scale = "tiny"',
                'family = "baseline"',
                'solver_family = ["modflow6"]',
                'region = "demo"',
                'tags = ["alpha", "fast"]',
                "",
                "[[campaign.case]]",
                'id = "demo_compare"',
                'launcher = "method-comparison"',
                'config = "configs/compare.toml"',
                'tier = "flagship"',
                'scale = "100km2"',
                'family = "visual_compare"',
                'solver_family = ["modflow6", "boussinesq"]',
                'region = "demo"',
                'tags = ["beta", "visual"]',
                "enabled = false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def test_load_and_filter_campaign_manifest(tmp_path: Path) -> None:
    manifest_path = _write_campaign_manifest(tmp_path)

    manifest = load_campaign_manifest(manifest_path)

    assert manifest.campaign_id == "demo_campaign"
    assert manifest.label == "Demo campaign"
    assert manifest.output_root == (tmp_path / "outputs").resolve()
    assert [case.case_id for case in manifest.cases] == ["demo_sim", "demo_compare"]
    assert manifest.cases[0].config_path == (tmp_path / "configs" / "sim.toml").resolve()

    selected = filter_campaign_cases(
        manifest.cases,
        tiers=("smoke",),
        tags=("alpha",),
    )
    assert [case.case_id for case in selected] == ["demo_sim"]

    with_disabled = filter_campaign_cases(
        manifest.cases,
        regions=("demo",),
        include_disabled=True,
    )
    assert [case.case_id for case in with_disabled] == ["demo_sim", "demo_compare"]


def test_build_run_command_dispatches_on_launcher(tmp_path: Path) -> None:
    manifest = load_campaign_manifest(_write_campaign_manifest(tmp_path))
    sim_case, compare_case = manifest.cases

    simulation_command = build_run_command(
        sim_case,
        python_executable=Path(sys.executable),
    )
    comparison_command = build_run_command(
        compare_case,
        python_executable=Path(sys.executable),
    )

    assert simulation_command == [
        str(Path(sys.executable)),
        "-m",
        "launchers",
        "simulation",
        str(sim_case.config_path),
    ]
    assert comparison_command == [
        str(Path(sys.executable)),
        "-m",
        "launchers",
        "method-comparison",
        "run",
        str(compare_case.config_path),
    ]


def test_build_execution_report_summarizes_runs(tmp_path: Path) -> None:
    manifest = load_campaign_manifest(_write_campaign_manifest(tmp_path))
    selected_cases = [manifest.cases[0]]

    report = build_execution_report(
        manifest=manifest,
        selected_cases=selected_cases,
        executions=[
            CampaignExecution(
                case=selected_cases[0],
                command=("python", "-m", "launchers", "simulation", "demo.toml"),
                returncode=0,
                duration_seconds=1.25,
            )
        ],
        filters={"tiers": ["smoke"]},
        continue_on_error=False,
    )

    assert report["campaign_id"] == "demo_campaign"
    assert report["selected_case_count"] == 1
    assert report["completed_case_count"] == 1
    assert report["failed_case_count"] == 0
    assert report["all_passed"] is True
    assert report["cases"][0]["id"] == "demo_sim"
    assert report["cases"][0]["duration_seconds"] == 1.25


def test_headwater_100km2_mf6_heterogeneous_decay_config_loads() -> None:
    config_path = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "projects"
        / "launcher_simulation"
        / "run_headwater_100km2_outlet_2_mf6_transient_heterogeneous_decay.toml"
    )

    payload = load_toml_with_base_config(config_path)
    assert payload["domain"]["supports"]["field_hydrofacies"]["provider"] == "generated_rings"
    assert payload["flow"]["param"]["K"]["field"]["kind"] == "heterogeneous"
    assert payload["simulation"]["time"]["end_datetime"] == "2005-12-31 00:00:00"

    cfg = HydroModPyConfig.from_toml(config_path)
    assert cfg.flow.flow_regime == "transient"
    assert cfg.capability_gallery.enabled is True
    assert cfg.domain.supports["field_hydrofacies"].provider == "generated_rings"


def test_headwater_100km2_mf6_scenario_comparison_config_loads() -> None:
    config_path = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "projects"
        / "launcher_simulation"
        / "run_method_comparison_headwater_100km2_outlet_2_mf6_transient_scenarios.toml"
    )

    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    assert cfg.method_comparison.comparison_id == "headwater_100km2_outlet_2_mf6_transient_scenarios"
    assert [variant.id for variant in cfg.method_comparison.variant] == [
        "mf6_reference",
        "mf6_heterogeneous_decay",
    ]
    assert [observable.name for observable in cfg.method_comparison.observable] == [
        "head_outlet_point",
        "outlet_flux_series",
        "watertable_depth_mean_last",
        "watertable_elevation_map",
        "watertable_depth_map",
    ]
