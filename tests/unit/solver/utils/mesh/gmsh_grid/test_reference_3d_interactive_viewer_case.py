from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_interactive_viewer import (
    build_reference_interactive_viewer_state_from_toml,
    run_reference_interactive_viewer_from_toml,
)

pytest.importorskip("pyvista")


CASE_TOML = (
    Path(__file__).resolve().parents[6]
    / "hydromodpy"
    / "solver"
    / "utils"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "reference_3d_fieldparam"
    / "case_interactive_viewer.toml"
)


def test_reference_3d_interactive_viewer_case_runs_off_screen():
    scratch_root = Path.cwd() / "scratch_tests" / "reference_3d_interactive_viewer"
    output_dir = scratch_root / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    state = build_reference_interactive_viewer_state_from_toml(CASE_TOML)
    mesh_with_values = state["mesh_with_values"]
    min_value = float(mesh_with_values.global_stats()["min"])
    max_value = float(mesh_with_values.global_stats()["max"])

    summary = run_reference_interactive_viewer_from_toml(
        CASE_TOML,
        show=False,
        off_screen=True,
        output_summary_json=output_dir / "reference_3d_interactive_summary.json",
        threshold_range=(min_value, max_value),
        highlight_source_cell_index=int(mesh_with_values.n_cells_2d // 2),
    )

    assert summary["n_cells_3d"] > 0
    assert summary["n_points_3d"] > 0
    assert summary["display_n_cells"] > 0
    assert "field_param_value" in summary["cell_data_keys"]
    assert "prism_center_depth" in summary["cell_data_keys"]
    assert Path(summary["output_summary_json"]).exists()
    assert summary["selection"]["source_cell_index"] == int(
        mesh_with_values.n_cells_2d // 2
    )
