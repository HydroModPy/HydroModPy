from __future__ import annotations

from pathlib import Path

from hydromodpy.analysis.testbed.runtime import TestbedLauncher as MethodTestbedLauncher
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

REPO_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_DIR = (
    REPO_ROOT / "examples" / "projects" / "10_testbed_workflow" / "boussinesq" / "natural_geology_k"
)
TESTBED_CONFIG = CAMPAIGN_DIR / "natural_petsc_vi_regression_testbed.toml"
BASE_COMPARISON = CAMPAIGN_DIR / "compare_natural_mf6_bouss_petsc_vi_base.toml"
SITE_CATALOG = CAMPAIGN_DIR / "natural_petsc_vi_regression_sites.csv"


def _isolated_testbed_config(tmp_path: Path) -> Path:
    output_root = (tmp_path / "outputs" / "boussinesq_petsc_vi_regression_testbed").resolve()
    text = TESTBED_CONFIG.read_text(encoding="utf-8")
    text = text.replace(
        'base_config = "compare_natural_mf6_bouss_petsc_vi_base.toml"',
        f'base_config = "{BASE_COMPARISON.as_posix()}"',
    )
    text = text.replace(
        'path = "natural_petsc_vi_regression_sites.csv"',
        f'path = "{SITE_CATALOG.as_posix()}"',
    )
    text = text.replace(
        "../../outputs/boussinesq_petsc_vi_regression_testbed",
        output_root.as_posix(),
    )
    config_path = tmp_path / "natural_petsc_vi_regression_testbed.toml"
    config_path.write_text(text, encoding="utf-8")
    return config_path


def _boussinesq_child(payload: dict[str, object]) -> dict[str, object]:
    simulations = payload["comparison"]["simulation"]  # type: ignore[index]
    for simulation in simulations:  # type: ignore[union-attr]
        if simulation.get("solver") == "boussinesq":
            return simulation
    raise AssertionError("Boussinesq comparison child not found")


def test_petsc_vi_regression_base_uses_only_direct_vi_obstacle() -> None:
    payload = load_toml_with_base_config(BASE_COMPARISON)
    bouss = _boussinesq_child(payload)
    flow = bouss["overlay"]["flow"]  # type: ignore[index]

    assert flow["runtime_backend"] == "petsc"
    assert flow["surface_interaction_model"] == "vi_obstacle"
    assert flow["vi_substeps_per_period"] == 4
    assert flow["vi_substep_on_failure"] is True
    assert flow["vi_max_adaptive_substeps"] == 32
    assert "ts_vi_steps_per_period" not in flow
    assert "ts_vi_type" not in flow
    assert "ts_vi_snes_type" not in flow


def test_petsc_vi_regression_testbed_materializes_multi_scale_comparisons(
    tmp_path: Path,
) -> None:
    summary = MethodTestbedLauncher(_isolated_testbed_config(tmp_path)).run()

    assert summary["variant_count"] == 6
    assert summary["executed_count"] == 0

    generated_dir = Path(summary["generated_configs_dir"])
    generated = sorted(generated_dir.glob("*.toml"))
    assert [path.stem for path in generated] == [
        "headwater_100km2_outlet_2",
        "headwater_100km2_outlet_4",
        "s3_100km2_outlet_25",
        "site_01",
        "site_03",
        "site_08",
    ]

    axes = set()
    for path in generated:
        payload = load_toml_with_base_config(path)
        comparison = payload["comparison"]
        axes.add("100km2" if "100km2" in comparison["comparison_id"] else "10km2")
        bouss = _boussinesq_child(payload)
        flow = bouss["overlay"]["flow"]  # type: ignore[index]
        assert flow["runtime_backend"] == "petsc"
        assert flow["surface_interaction_model"] == "vi_obstacle"
        assert flow["vi_substeps_per_period"] == 4
        assert "ts_vi_steps_per_period" not in flow
        assert "ts_vi_type" not in flow
        assert "ts_vi_snes_type" not in flow

    assert axes == {"10km2", "100km2"}


def test_petsc_vi_regression_100km2_rule_overrides_scale_settings(tmp_path: Path) -> None:
    summary = MethodTestbedLauncher(_isolated_testbed_config(tmp_path)).run()
    generated_dir = Path(summary["generated_configs_dir"])
    payload = load_toml_with_base_config(generated_dir / "headwater_100km2_outlet_2.toml")
    comparison = payload["comparison"]

    assert comparison["execution"]["timeout_seconds"] == 7200
    assert comparison["fine_raster"]["resolution"] == 160.0

    base_overlay = comparison["base_simulation_overlay"]
    assert base_overlay["geographic"]["snap_dist"] == "300.0 m"
    assert base_overlay["geographic"]["buff_area"] == "1800.0 m"
    assert base_overlay["geographic"]["river_network"]["enabled"] is False
    assert "mesh_catchment" not in base_overlay
    assert base_overlay["data"]["types"] == ["dem", "geology", "recharge"]
    assert base_overlay["mesh_input"]["bundle_dir"].endswith(
        "examples/projects/07_mesh_gallery/100km2/"
        "mesh_headwater_100km2_outlet_2_geology_rivers_buffer30/bundle"
    )
    for simulation in comparison["simulation"]:
        assert simulation["mesh_mode"] == "mesh_input"
        assert simulation["mesh_label"] == "precomputed mesh-gallery geology-river bundle"
