"""Validate PETSc Boussinesq variants on one transient real headwater basin."""

from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

from hydromodpy.project import Project


def _require_linux_petsc4py() -> None:
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")


def _write_overlay_config(
    *,
    tmp_path: Path,
    base_config: Path,
    project_root: Path,
    dem_init_path: Path,
    mesh_path: Path,
    bundle_dir: Path,
) -> Path:
    config_path = tmp_path / f"{base_config.stem}_overlay.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                f'base_config = "{base_config.as_posix()}"',
                "",
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{project_root.as_posix()}"',
                "",
                "[geographic]",
                f'dem_init_path = "{dem_init_path.as_posix()}"',
                "",
                "[mesh_input]",
                f'mesh_path = "{mesh_path.as_posix()}"',
                f'bundle_dir = "{bundle_dir.as_posix()}"',
                "",
                "[display]",
                "show = false",
                "save = false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _run_transient_real_case_summary(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_name: str,
) -> dict[str, object]:
    _require_linux_petsc4py()

    repo_root = Path(__file__).resolve().parents[4]
    base_dir = repo_root / "examples_legacy_2" / "projects" / "launcher_simulation"
    base_config = base_dir / config_name
    project_root = tmp_path / base_config.stem
    config_path = _write_overlay_config(
        tmp_path=tmp_path,
        base_config=base_config,
        project_root=project_root,
        dem_init_path=(base_dir / "../../data/dem/DEM_armorican_massif.tif").resolve(),
        mesh_path=(
            base_dir
            / "../../mesh_gallery/100km2/mesh_headwater_100km2_outlet_2_geology_rivers_buffer30/bundle/mesh_2d.msh"
        ).resolve(),
        bundle_dir=(
            base_dir
            / "../../mesh_gallery/100km2/mesh_headwater_100km2_outlet_2_geology_rivers_buffer30/bundle"
        ).resolve(),
    )

    monkeypatch.setenv("MPLBACKEND", "Agg")

    with Project(config_path) as project:
        project.run()
    model = project._ctx.get_model_for_solver("boussinesq")
    assert model is not None
    assert model.has_numerical_solution is True

    summary_path = Path(model.full_path) / "_boussinesq_summary.json"
    assert summary_path.exists()
    return json.loads(summary_path.read_text(encoding="utf-8"))


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.petsc
@pytest.mark.parametrize(
    ("config_name", "expected_surface_model"),
    [
        pytest.param(
            "run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_pulsed_recharge.toml",
            "regularized_partition",
            id="petsc_partition",
        ),
        pytest.param(
            "run_headwater_100km2_outlet_2_boussinesq_petsc_transient_pulsed_recharge.toml",
            "complementarity",
            id="petsc_complementarity",
        ),
    ],
)
def test_headwater_transient_real_case_petsc_variants_converge_on_committed_mesh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_name: str,
    expected_surface_model: str,
) -> None:
    summary = _run_transient_real_case_summary(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        config_name=config_name,
    )

    assert summary["runtime_backend"] == "petsc"
    assert summary["surface_interaction_model_resolved"] == expected_surface_model
    assert int(summary["n_periods"]) == 8
    assert all(bool(flag) for flag in summary["converged_by_period"])
    assert float(summary["last_residual_norm_inf"]) <= float(summary["runtime_tol_residual_inf"])
    assert summary["surface_threshold_active_any"] is True
    assert int(summary["surface_threshold_active_steps"]) > 0
    assert int(summary["surface_threshold_activation_windows"]) >= 1
    assert int(summary["surface_threshold_state_transitions"]) >= 1
    assert int(summary["surface_threshold_peak_active_cells"]) > 100
    assert float(summary["surface_threshold_peak_total_m3_day"]) > 1.0e5

    if expected_surface_model == "complementarity":
        assert float(summary["surface_complementarity_min_gap_m"]) >= -1.0e-6
        assert float(summary["surface_complementarity_min_rate_m_s"]) >= -1.0e-6
        assert float(summary["surface_complementarity_peak_overlap_m2_s"]) <= 1.0e-8
    else:
        assert "surface_complementarity_min_gap_m" not in summary


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.petsc
def test_headwater_transient_cycling_real_case_distinguishes_surface_closures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partition_summary = _run_transient_real_case_summary(
        tmp_path=tmp_path / "partition",
        monkeypatch=monkeypatch,
        config_name="run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_cycling_recharge.toml",
    )
    mixed_summary = _run_transient_real_case_summary(
        tmp_path=tmp_path / "mixed",
        monkeypatch=monkeypatch,
        config_name="run_headwater_100km2_outlet_2_boussinesq_petsc_transient_cycling_recharge.toml",
    )

    assert partition_summary["runtime_backend"] == "petsc"
    assert mixed_summary["runtime_backend"] == "petsc"
    assert partition_summary["surface_interaction_model_resolved"] == "regularized_partition"
    assert mixed_summary["surface_interaction_model_resolved"] == "complementarity"
    assert int(partition_summary["n_periods"]) == 12
    assert int(mixed_summary["n_periods"]) == 12
    assert all(bool(flag) for flag in partition_summary["converged_by_period"])
    assert all(bool(flag) for flag in mixed_summary["converged_by_period"])
    assert float(partition_summary["last_residual_norm_inf"]) <= float(
        partition_summary["runtime_tol_residual_inf"]
    )
    assert float(mixed_summary["last_residual_norm_inf"]) <= float(
        mixed_summary["runtime_tol_residual_inf"]
    )

    # The head-only regularized-partition path keeps one low-amplitude seepage
    # window active throughout the whole sequence, while the mixed
    # complementarity solve turns the threshold off between wet pulses.
    assert int(partition_summary["surface_threshold_activation_windows"]) == 1
    assert int(partition_summary["surface_threshold_active_steps"]) == int(
        partition_summary["n_periods"]
    )
    assert int(mixed_summary["surface_threshold_activation_windows"]) >= 5
    assert int(mixed_summary["surface_threshold_deactivation_windows"]) >= 4
    assert int(mixed_summary["surface_threshold_active_steps"]) <= 6
    assert int(mixed_summary["surface_threshold_state_transitions"]) >= 9
    assert int(mixed_summary["surface_threshold_peak_active_cells"]) < int(
        partition_summary["surface_threshold_peak_active_cells"]
    )
    assert float(mixed_summary["surface_threshold_peak_total_m3_day"]) > 2.0e4
    assert int(mixed_summary["surface_threshold_final_active_cells"]) == 0
    assert float(mixed_summary["surface_complementarity_min_gap_m"]) >= -1.0e-6
    assert float(mixed_summary["surface_complementarity_min_rate_m_s"]) >= -1.0e-6
    assert float(mixed_summary["surface_complementarity_peak_overlap_m2_s"]) <= 1.0e-8


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.petsc
def test_headwater_transient_cycling_heterogeneous_real_case_distinguishes_surface_closures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partition_summary = _run_transient_real_case_summary(
        tmp_path=tmp_path / "partition_heterogeneous",
        monkeypatch=monkeypatch,
        config_name="run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_cycling_recharge_heterogeneous.toml",
    )
    mixed_summary = _run_transient_real_case_summary(
        tmp_path=tmp_path / "mixed_heterogeneous",
        monkeypatch=monkeypatch,
        config_name="run_headwater_100km2_outlet_2_boussinesq_petsc_transient_cycling_recharge_heterogeneous.toml",
    )

    assert partition_summary["runtime_backend"] == "petsc"
    assert mixed_summary["runtime_backend"] == "petsc"
    assert partition_summary["surface_interaction_model_resolved"] == "regularized_partition"
    assert mixed_summary["surface_interaction_model_resolved"] == "complementarity"
    assert int(partition_summary["n_periods"]) == 12
    assert int(mixed_summary["n_periods"]) == 12
    assert all(bool(flag) for flag in partition_summary["converged_by_period"])
    assert all(bool(flag) for flag in mixed_summary["converged_by_period"])
    assert float(partition_summary["last_residual_norm_inf"]) <= float(
        partition_summary["runtime_tol_residual_inf"]
    )
    assert float(mixed_summary["last_residual_norm_inf"]) <= float(
        mixed_summary["runtime_tol_residual_inf"]
    )

    # Strong lateral contrasts keep the head-only seepage closure partially
    # active even after the last dry pulse, while the mixed complementarity path
    # still switches the threshold off between wetting episodes.
    assert int(partition_summary["surface_threshold_activation_windows"]) == 1
    assert int(partition_summary["surface_threshold_active_steps"]) == int(
        partition_summary["n_periods"]
    )
    assert int(partition_summary["surface_threshold_peak_active_cells"]) >= 500
    assert int(partition_summary["surface_threshold_final_active_cells"]) >= 100
    assert float(partition_summary["surface_threshold_peak_total_m3_day"]) >= 5.0e4

    assert int(mixed_summary["surface_threshold_activation_windows"]) >= 5
    assert int(mixed_summary["surface_threshold_deactivation_windows"]) >= 5
    assert int(mixed_summary["surface_threshold_active_steps"]) <= 6
    assert int(mixed_summary["surface_threshold_state_transitions"]) >= 9
    assert int(mixed_summary["surface_threshold_peak_active_cells"]) >= 150
    assert int(mixed_summary["surface_threshold_peak_active_cells"]) < int(
        partition_summary["surface_threshold_peak_active_cells"]
    )
    assert float(mixed_summary["surface_threshold_peak_total_m3_day"]) >= 5.0e4
    assert int(mixed_summary["surface_threshold_final_active_cells"]) == 0
    assert float(mixed_summary["surface_complementarity_min_gap_m"]) >= -1.0e-6
    assert float(mixed_summary["surface_complementarity_min_rate_m_s"]) >= -1.0e-6
    assert float(mixed_summary["surface_complementarity_peak_overlap_m2_s"]) <= 1.0e-8
