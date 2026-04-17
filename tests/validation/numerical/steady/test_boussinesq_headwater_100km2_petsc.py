"""Validate PETSc Boussinesq variants on one committed real headwater basin."""

from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

from hydromodpy.project import Simulation


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
    config_path.write_text(
        "\n".join(
            [
                f'base_config = "{base_config.as_posix()}"',
                "",
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


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.slow
@pytest.mark.petsc
@pytest.mark.parametrize(
    ("config_name", "expected_surface_model"),
    [
        pytest.param(
            "run_headwater_100km2_outlet_2_boussinesq_petsc_partition_mesh_input.toml",
            "regularized_partition",
            id="petsc_partition",
        ),
        pytest.param(
            "run_headwater_100km2_outlet_2_boussinesq_petsc_mesh_input.toml",
            "complementarity",
            id="petsc_complementarity",
        ),
    ],
)
def test_headwater_real_case_petsc_variants_converge_on_committed_mesh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_name: str,
    expected_surface_model: str,
) -> None:
    _require_linux_petsc4py()

    repo_root = Path(__file__).resolve().parents[4]
    base_config = (
        repo_root
        / "examples"
        / "projects"
        / "launcher_simulation"
        / config_name
    )
    base_dir = base_config.parent
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

    monkeypatch.setenv("HYDROMODPY_NO_DISPLAY", "1")
    monkeypatch.setenv("HYDROMODPY_NO_SAVE", "1")
    monkeypatch.setenv("MPLBACKEND", "Agg")

    with Simulation(config_path) as project:
        project.run()
    model = project._ctx.get_model_for_solver("boussinesq")
    assert model is not None
    assert model.has_numerical_solution is True

    summary_path = Path(model.full_path) / "_boussinesq_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["runtime_backend"] == "petsc"
    assert summary["surface_interaction_model_resolved"] == expected_surface_model
    assert int(summary["steady_nonlinear_iterations"]) > 0
    assert summary["surface_threshold_active_any"] is True
    assert int(summary["surface_threshold_peak_active_cells"]) > 50
    assert float(summary["surface_threshold_peak_total_m3_day"]) > 1.0e3

    if expected_surface_model == "complementarity":
        assert float(summary["surface_complementarity_min_gap_m"]) >= -1.0e-6
        assert float(summary["surface_complementarity_min_rate_m_s"]) >= -1.0e-6
        assert float(summary["surface_complementarity_peak_overlap_m2_s"]) <= 1.0e-8
    else:
        assert "surface_complementarity_min_gap_m" not in summary
