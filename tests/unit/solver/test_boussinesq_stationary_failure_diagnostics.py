from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.solver_diagnostics import (
    STATIONARY_FAILURE_ACTIVE_SET_SUMMARY_CSV,
    STATIONARY_FAILURE_CELLS_TOP_RESIDUAL_CSV,
    STATIONARY_FAILURE_FIELD_STATS_JSON,
    STATIONARY_FAILURE_SUMMARY_JSON,
)
from hydromodpy.solver.boussinesq.assembly import assemble_steady_residual
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    RuntimeSolveResult,
)
from hydromodpy.solver.boussinesq.runtimes.stationary_failure_diagnostics import (
    write_stationary_failure_diagnostics,
)


def _two_cell_mesh() -> BoussinesqMesh:
    return BoussinesqMesh(
        bundle_dir=Path("."),
        cell_ids=np.asarray([10, 11], dtype=int),
        node_ids=np.asarray([0, 1, 2, 3], dtype=int),
        node_x_m=np.asarray([0.0, 1.0, 0.0, 1.0], dtype=float),
        node_y_m=np.asarray([0.0, 0.0, 1.0, 1.0], dtype=float),
        cell_node_ids=((0, 1, 2), (1, 3, 2)),
        cell_centroid_x_m=np.asarray([0.33, 0.67], dtype=float),
        cell_centroid_y_m=np.asarray([0.33, 0.67], dtype=float),
        cell_area_m2=np.asarray([100.0, 200.0], dtype=float),
        z_top_m=np.asarray([10.0, 12.0], dtype=float),
        z_bottom_m=np.asarray([0.0, 1.0], dtype=float),
        hydraulic_conductivity_m_s=np.asarray([1.0e-4, 2.0e-4], dtype=float),
        storage_coefficient=np.asarray([0.1, 0.1], dtype=float),
        edge_ids=np.asarray([0], dtype=int),
        edge_node_a=np.asarray([1], dtype=int),
        edge_node_b=np.asarray([2], dtype=int),
        edge_cell_a=np.asarray([0], dtype=int),
        edge_cell_b=np.asarray([1], dtype=int),
        edge_length_m=np.asarray([1.0], dtype=float),
        edge_distance_m=np.asarray([1.0], dtype=float),
        edge_midpoint_distance_to_cell_a_m=np.asarray([0.5], dtype=float),
        edge_midpoint_distance_to_cell_b_m=np.asarray([0.5], dtype=float),
        edge_midpoint_x_m=np.asarray([0.5], dtype=float),
        edge_midpoint_y_m=np.asarray([0.5], dtype=float),
        edge_kind=("internal",),
        edge_is_river=np.asarray([False], dtype=bool),
        cell_index_by_id={10: 0, 11: 1},
        node_index_by_id={0: 0, 1: 1, 2: 2, 3: 3},
    )


def test_stationary_failure_diagnostics_are_serializable(tmp_path: Path) -> None:
    mesh = _two_cell_mesh()
    head = np.asarray([10.0, 1.0], dtype=float)
    assembly = assemble_steady_residual(
        mesh,
        head_m=head,
        recharge_rate_m_s=np.asarray([1.0e-8, 2.0e-8], dtype=float),
        drainage_conductance_m2_s=np.asarray([0.0, 0.1], dtype=float),
    )
    result = RuntimeSolveResult(
        head_m=head,
        assembly=assembly,
        converged=False,
        iterations=3,
        residual_norm_inf=4.2,
        backend_name="petsc",
        termination_reason="petsc SNESVI failed reason -6 (SNES_DIVERGED_LINE_SEARCH)",
        diagnostics=None,
    )
    runtime_backend = SimpleNamespace(
        name="petsc",
        engine_id="petsc_vi_obstacle_snes",
        method=SimpleNamespace(id="head_only_vi_obstacle"),
    )

    paths = write_stationary_failure_diagnostics(
        tmp_path,
        mesh=mesh,
        result=result,
        runtime_backend=runtime_backend,
        options=NonlinearRuntimeOptions(
            regularization_radius=0.05,
            max_iterations=20,
            tol_residual_inf=1.0e-9,
        ),
        runtime_summary={
            "surface_interaction_model_resolved": "vi_obstacle",
            "steady_snes_converged_reason_label": "SNES_DIVERGED_LINE_SEARCH",
            "steady_snes_type": "vinewtonrsls",
            "steady_ksp_type": "preonly",
            "steady_pc_type": "lu",
        },
        case_id="unit_case",
        simulation_id="unit_sim",
        initialization_strategy={"source": "mean_recharge"},
        recharge_rate_m_s=np.asarray([1.0e-8, 2.0e-8], dtype=float),
        drainage_conductance_m2_s=np.asarray([0.0, 0.1], dtype=float),
        top_n_cells=2,
    )

    expected_names = {
        "summary": STATIONARY_FAILURE_SUMMARY_JSON,
        "cells_top_residual": STATIONARY_FAILURE_CELLS_TOP_RESIDUAL_CSV,
        "active_set_summary": STATIONARY_FAILURE_ACTIVE_SET_SUMMARY_CSV,
        "field_stats": STATIONARY_FAILURE_FIELD_STATS_JSON,
    }
    assert {key: Path(value).name for key, value in paths.items()} == expected_names
    for path in paths.values():
        assert Path(path).exists()

    summary = json.loads((tmp_path / STATIONARY_FAILURE_SUMMARY_JSON).read_text())
    assert summary["case_id"] == "unit_case"
    assert summary["converged"] is False
    assert summary["snes_reason"] == "SNES_DIVERGED_LINE_SEARCH"
    assert summary["active_top_count"] == 1
    assert summary["active_bottom_count"] == 1
    assert summary["projected_residual_norm_final"] is not None

    with (tmp_path / STATIONARY_FAILURE_CELLS_TOP_RESIDUAL_CSV).open(
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {row["active_state"] for row in rows} == {"top", "bottom"}
    assert {row["cell_id"] for row in rows} == {"10", "11"}

    active_rows = list(
        csv.DictReader(
            (tmp_path / STATIONARY_FAILURE_ACTIVE_SET_SUMMARY_CSV).open(
                encoding="utf-8",
                newline="",
            )
        )
    )
    assert {row["active_state"] for row in active_rows} == {"top", "bottom"}

    stats = json.loads((tmp_path / STATIONARY_FAILURE_FIELD_STATS_JSON).read_text())
    assert stats["transmissivity"]["max"] == pytest.approx(0.001)
