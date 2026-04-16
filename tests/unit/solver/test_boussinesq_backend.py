from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.process.flow import Flow
from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.solver.boussinesq import Boussinesq, BoussinesqMesh
from hydromodpy.solver.boussinesq.assembly import (
    assemble_steady_residual,
    assemble_steady_residual_with_saturation_excess,
    assemble_transient_residual,
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.jacobian_fd import (
    build_cell_coupling_rows_by_column,
    build_colored_sparse_fd_jacobian_triplets,
    build_dense_fd_jacobian,
    color_columns_by_row_overlap,
)
from hydromodpy.solver.boussinesq.jacobian_semianalytic import (
    build_sparse_semianalytic_base_jacobian_triplets,
    build_sparse_semianalytic_regularized_partition_jacobian_triplets,
)
from hydromodpy.solver.boussinesq.local_runtime import (
    solve_backward_euler_step,
    solve_steady_state,
)
from hydromodpy.solver.boussinesq.petsc_runtime import (
    _coo_to_csr,
    _fischer_burmeister_residual_and_derivatives,
    _initial_transient_q_ex_guess,
    solve_steady_problem as solve_steady_problem_petsc,
)
from hydromodpy.solver.boussinesq.partition_runtime_utils import (
    interiorize_regularized_partition_initial_guess,
    regularized_partition_jacobian_shift,
)
from hydromodpy.solver.boussinesq.runtime_contract import SteadySolveInputs
from hydromodpy.solver.boussinesq.runtime_selection import resolve_runtime_backend
from hydromodpy.solver.boussinesq.scipy_runtime import (
    solve_steady_problem as solve_steady_problem_scipy,
)
from hydromodpy.solver.boussinesq.scipy_sparse_runtime import (
    solve_steady_problem as solve_steady_problem_scipy_sparse,
)
from hydromodpy.solver.prototype.solver_config import SolverConfig
from hydromodpy.solver.prototype.solver_engine import SolverEngine
from hydromodpy.solver.utils.mesh.gmsh_grid import GmshPlanarMesh2D
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _write_minimal_bundle(
    bundle_dir: Path,
    *,
    storage_in_second_cell: bool = True,
    river_internal_edge: bool = False,
) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mesh_2d.msh").write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "files": {"mesh": "mesh_2d.msh"},
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "mesh_summary.json").write_text(
        json.dumps({"constraints_mode": "geology_only"}, indent=2, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        bundle_dir / "nodes.csv",
        "node_id,x,y,z_top,z_bottom",
        [
            "0,0.0,0.0,10.0,5.0",
            "1,1.0,0.0,10.0,5.0",
            "2,1.0,1.0,10.0,5.0",
            "3,0.0,1.0,10.0,5.0",
        ],
    )
    second_storage = "0.15" if storage_in_second_cell else ""
    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
        [
            "0,triangle,0,1,2,,0.666667,0.333333,0.5,10.0,10.0,5.0,5.0,1,granite,1.0e-5,0.10",
            f"1,triangle,0,2,3,,0.333333,0.666667,0.5,11.0,11.0,4.0,4.0,2,schist,2.0e-5,{second_storage}",
        ],
    )
    _write_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
        [
            "0,0,1,0,,1.0,boundary,false,granite,",
            "1,1,2,0,,1.0,boundary,false,granite,",
            f"2,0,2,0,1,1.414214,internal,{str(bool(river_internal_edge)).lower()},granite,schist",
            "3,2,3,1,,1.0,boundary,false,schist,",
            "4,0,3,1,,1.0,boundary,false,schist,",
        ],
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        [
            "0,granite,1.0",
            "1,schist,1.0",
        ],
    )
    return bundle_dir


def _build_flow_config(flow_section: dict[str, object]) -> FlowConfig:
    return FlowConfig.from_toml_section(flow_section, base_dir=Path("."))


def _build_planar_mesh() -> GmshPlanarMesh2D:
    return GmshPlanarMesh2D(
        points_xy=np.asarray(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        connectivity=np.asarray(
            [
                [0, 1, 2],
                [0, 2, 3],
            ],
            dtype=int,
        ),
        cell_type="triangle",
    )


def _make_static_recharge_field_record() -> FieldRecord:
    ds = xr.Dataset(
        {
            "recharge": (
                ("y", "x"),
                np.asarray(
                    [
                        [1.0e-7, 4.0e-7],
                        [2.0e-7, 3.0e-7],
                    ],
                    dtype=float,
                ),
            )
        },
        coords={
            "x": np.asarray([0.333333, 0.666667], dtype=float),
            "y": np.asarray([0.333333, 0.666667], dtype=float),
        },
    )
    return FieldRecord(
        variable="recharge",
        source="test",
        unit="m/s",
        data=ds,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
    )


def _triplets_to_dense(
    data: np.ndarray,
    row_indices: np.ndarray,
    col_indices: np.ndarray,
    *,
    shape: tuple[int, int],
) -> np.ndarray:
    matrix = np.zeros(shape, dtype=float)
    np.add.at(
        matrix,
        (
            np.asarray(row_indices, dtype=int),
            np.asarray(col_indices, dtype=int),
        ),
        np.asarray(data, dtype=float),
    )
    return matrix


def test_solver_config_accepts_boussinesq() -> None:
    cfg = SolverConfig(solver_engine="boussinesq")

    assert cfg.solver_engine == SolverEngine.BOUSSINESQ


@pytest.mark.parametrize("runtime_backend", ["scipy", "scipy_sparse", "petsc"])
def test_flow_config_accepts_boussinesq_runtime_backend(runtime_backend: str) -> None:
    cfg = FlowConfig.model_validate({"runtime_backend": runtime_backend})
    flow = Flow(cfg)

    assert cfg.runtime_backend == runtime_backend
    assert flow.runtime_backend == runtime_backend


@pytest.mark.parametrize(
    "surface_interaction_model",
    ["auto", "regularized_partition", "complementarity"],
)
def test_flow_config_accepts_surface_interaction_model(
    surface_interaction_model: str,
) -> None:
    cfg = FlowConfig.model_validate(
        {"surface_interaction_model": surface_interaction_model}
    )
    flow = Flow(cfg)

    assert cfg.surface_interaction_model == surface_interaction_model
    assert flow.surface_interaction_model == surface_interaction_model


def test_runtime_selection_routes_petsc_by_surface_interaction_model() -> None:
    partition_backend = resolve_runtime_backend(
        "petsc",
        surface_interaction_model="regularized_partition",
    )
    complementarity_backend = resolve_runtime_backend(
        "petsc",
        surface_interaction_model="complementarity",
    )

    assert partition_backend.name == "petsc"
    assert complementarity_backend.name == "petsc"
    assert "regularized_partition" in partition_backend.nonlinear_solver_kind
    assert "fischer_burmeister" in complementarity_backend.nonlinear_solver_kind


def test_runtime_selection_rejects_complementarity_without_petsc() -> None:
    with pytest.raises(NotImplementedError):
        resolve_runtime_backend(
            "scipy_sparse",
            surface_interaction_model="complementarity",
        )


def test_flow_config_accepts_boussinesq_runtime_overrides() -> None:
    cfg = FlowConfig.model_validate(
        {
            "runtime_backend": "scipy_sparse",
            "runtime_max_iterations": 60,
            "runtime_tol_residual_inf": 1.0e-7,
            "runtime_tol_state_update_inf": 1.0e-8,
        }
    )
    flow = Flow(cfg)

    assert cfg.runtime_max_iterations == 60
    assert cfg.runtime_tol_residual_inf == pytest.approx(1.0e-7)
    assert cfg.runtime_tol_state_update_inf == pytest.approx(1.0e-8)
    assert flow.runtime_max_iterations == 60
    assert flow.runtime_tol_residual_inf == pytest.approx(1.0e-7)
    assert flow.runtime_tol_state_update_inf == pytest.approx(1.0e-8)


def test_fischer_burmeister_residual_vanishes_on_complementary_states() -> None:
    residual, dphi_dh, dphi_dq = _fischer_burmeister_residual_and_derivatives(
        np.asarray([0.0, 2.5e-6], dtype=float),
        np.asarray([1.2, 0.0], dtype=float),
        head_scale_m=2.0,
        rate_scale_m_s=5.0e-6,
    )

    assert np.allclose(residual, 0.0)
    assert np.isfinite(dphi_dh).all()
    assert np.isfinite(dphi_dq).all()


def test_transient_mixed_petsc_q_ex_initial_guess_starts_dry_without_positive_source(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))

    q_ex_initial = _initial_transient_q_ex_guess(
        mesh,
        head_initial_guess_m=np.asarray([10.0, 11.0], dtype=float),
        head_prev_m=np.asarray([10.0, 11.0], dtype=float),
        dt_seconds=3600.0,
        recharge_rate_m_s=0.0,
        well_flux_m3_s=0.0,
        imposed_head_m_by_edge=None,
        drainage_conductance_m2_s=0.0,
        regularization_radius=0.05,
    )

    assert q_ex_initial.shape == (mesh.n_cells,)
    assert np.allclose(q_ex_initial, 0.0)


def test_transient_mixed_petsc_q_ex_initial_guess_uses_partition_predictor_with_recharge(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head_initial = np.asarray([10.0, 11.0], dtype=float)

    q_ex_initial = _initial_transient_q_ex_guess(
        mesh,
        head_initial_guess_m=head_initial,
        head_prev_m=head_initial,
        dt_seconds=3600.0,
        recharge_rate_m_s=2.0e-7,
        well_flux_m3_s=0.0,
        imposed_head_m_by_edge=None,
        drainage_conductance_m2_s=0.0,
        regularization_radius=0.05,
    )
    reference = np.maximum(
        np.asarray(
            assemble_transient_residual(
                mesh,
                head_m=head_initial,
                head_prev_m=head_initial,
                dt_seconds=3600.0,
                recharge_rate_m_s=2.0e-7,
                well_flux_m3_s=0.0,
                imposed_head_m_by_edge=None,
                drainage_conductance_m2_s=0.0,
                regularization_radius=0.05,
            ).saturation_excess_rate_m_s,
            dtype=float,
        ),
        0.0,
    )

    assert np.allclose(q_ex_initial, reference)


def test_prescribed_saturation_excess_overrides_regularized_balance(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    prescribed_q_ex = np.asarray([1.5e-7, 3.0e-7], dtype=float)

    assembly = assemble_steady_residual_with_saturation_excess(
        mesh,
        head_m=np.asarray([10.0, 10.5], dtype=float),
        saturation_excess_rate_m_s=prescribed_q_ex,
        recharge_rate_m_s=2.0e-7,
    )

    assert np.allclose(assembly.saturation_excess_rate_m_s, prescribed_q_ex)


def test_coo_to_csr_uses_requested_index_dtype() -> None:
    indptr, indices, values = _coo_to_csr(
        n_rows=2,
        n_cols=2,
        row_indices=np.asarray([0, 0, 1], dtype=np.int64),
        col_indices=np.asarray([0, 1, 1], dtype=np.int64),
        data=np.asarray([1.0, 2.0, 3.0], dtype=float),
        index_dtype=np.int32,
    )

    assert indptr.dtype == np.int32
    assert indices.dtype == np.int32
    assert np.allclose(values, np.asarray([1.0, 2.0, 3.0], dtype=float))


def test_petsc_runtime_rejects_non_linux_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    monkeypatch.setattr(
        "hydromodpy.solver.boussinesq.petsc_common.platform.system",
        lambda: "Windows",
    )

    with pytest.raises(RuntimeError, match="only supported on Linux"):
        solve_steady_problem_petsc(
            SteadySolveInputs(
                mesh=mesh,
                head_initial_guess_m=np.full(mesh.n_cells, 7.0, dtype=float),
            )
        )


def test_sparse_fd_coloring_groups_only_disjoint_columns() -> None:
    rows_by_col = (
        np.asarray([0], dtype=int),
        np.asarray([0, 1], dtype=int),
        np.asarray([1, 2], dtype=int),
        np.asarray([2, 3], dtype=int),
    )

    groups = color_columns_by_row_overlap(rows_by_col)

    assert len(groups) == 2
    assert sorted(np.concatenate(groups).tolist()) == [0, 1, 2, 3]
    for group in groups:
        seen_rows: set[int] = set()
        for col in np.asarray(group, dtype=int).tolist():
            active_rows = set(np.asarray(rows_by_col[col], dtype=int).tolist())
            assert seen_rows.isdisjoint(active_rows)
            seen_rows.update(active_rows)


def test_colored_sparse_fd_jacobian_matches_dense_with_fewer_residual_calls() -> None:
    rows_by_col = (
        np.asarray([0], dtype=int),
        np.asarray([0, 1], dtype=int),
        np.asarray([1, 2], dtype=int),
        np.asarray([2, 3], dtype=int),
    )
    groups = color_columns_by_row_overlap(rows_by_col)
    head = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=float)
    matrix = np.asarray(
        [
            [2.0, 3.0, 0.0, 0.0],
            [0.0, -1.0, 5.0, 0.0],
            [0.0, 0.0, 7.0, -1.0],
            [0.0, 0.0, 0.0, 11.0],
        ],
        dtype=float,
    )
    offset = np.asarray([0.5, -1.0, 2.0, 3.0], dtype=float)

    dense_calls = {"count": 0}

    def residual_dense(candidate_head: np.ndarray) -> np.ndarray:
        dense_calls["count"] += 1
        return matrix @ np.asarray(candidate_head, dtype=float) + offset

    sparse_calls = {"count": 0}

    def residual_sparse(candidate_head: np.ndarray) -> np.ndarray:
        sparse_calls["count"] += 1
        return matrix @ np.asarray(candidate_head, dtype=float) + offset

    residual0_dense = residual_dense(head)
    residual0_sparse = residual_sparse(head)
    dense_jacobian = build_dense_fd_jacobian(
        residual_dense,
        head,
        residual0_dense,
        rel_step=1.0e-7,
    )
    data, row_indices, col_indices = build_colored_sparse_fd_jacobian_triplets(
        residual_sparse,
        head,
        residual0_sparse,
        rows_by_col=rows_by_col,
        column_groups=groups,
        rel_step=1.0e-7,
    )
    sparse_jacobian = np.zeros_like(dense_jacobian)
    sparse_jacobian[row_indices, col_indices] = data

    assert np.allclose(sparse_jacobian, matrix)
    assert np.allclose(sparse_jacobian, dense_jacobian)
    assert sparse_calls["count"] == 1 + len(groups)
    assert dense_calls["count"] == 1 + head.size


def test_semianalytic_steady_base_jacobian_matches_dense_fd_without_saturation_excess(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head = np.asarray([8.2, 8.9], dtype=float)
    imposed_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    imposed_heads[mesh.boundary_edge_indices_for_side("west_side")] = 10.0
    imposed_heads[mesh.boundary_edge_indices_for_side("east_side")] = 6.0

    def residual_fn(candidate_head: np.ndarray) -> np.ndarray:
        return assemble_steady_residual(
            mesh,
            head_m=candidate_head,
            imposed_head_m_by_edge=imposed_heads,
            regularization_radius=1.0e-6,
        ).residual_m3_s

    residual0 = residual_fn(head)
    assembly0 = assemble_steady_residual(
        mesh,
        head_m=head,
        imposed_head_m_by_edge=imposed_heads,
        regularization_radius=1.0e-6,
    )
    dense_jacobian = build_dense_fd_jacobian(
        residual_fn,
        head,
        residual0,
        rel_step=1.0e-7,
    )
    data, row_indices, col_indices = build_sparse_semianalytic_base_jacobian_triplets(
        mesh,
        head,
        imposed_head_m_by_edge=imposed_heads,
    )
    semianalytic_jacobian = _triplets_to_dense(
        data,
        row_indices,
        col_indices,
        shape=(mesh.n_cells, mesh.n_cells),
    )

    assert np.allclose(assembly0.saturation_excess_rate_m_s, 0.0)
    assert np.allclose(semianalytic_jacobian, dense_jacobian, atol=1.0e-8)


def test_semianalytic_transient_base_jacobian_matches_dense_fd_without_saturation_excess(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head_prev = np.asarray([8.0, 8.5], dtype=float)
    head = np.asarray([8.2, 8.9], dtype=float)
    imposed_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    imposed_heads[mesh.boundary_edge_indices_for_side("west_side")] = 10.0
    imposed_heads[mesh.boundary_edge_indices_for_side("east_side")] = 6.0

    def residual_fn(candidate_head: np.ndarray) -> np.ndarray:
        return assemble_transient_residual(
            mesh,
            head_m=candidate_head,
            head_prev_m=head_prev,
            dt_seconds=3600.0,
            imposed_head_m_by_edge=imposed_heads,
            regularization_radius=1.0e-6,
        ).residual_m3_s

    residual0 = residual_fn(head)
    assembly0 = assemble_transient_residual(
        mesh,
        head_m=head,
        head_prev_m=head_prev,
        dt_seconds=3600.0,
        imposed_head_m_by_edge=imposed_heads,
        regularization_radius=1.0e-6,
    )
    dense_jacobian = build_dense_fd_jacobian(
        residual_fn,
        head,
        residual0,
        rel_step=1.0e-7,
    )
    data, row_indices, col_indices = build_sparse_semianalytic_base_jacobian_triplets(
        mesh,
        head,
        dt_seconds=3600.0,
        imposed_head_m_by_edge=imposed_heads,
    )
    semianalytic_jacobian = _triplets_to_dense(
        data,
        row_indices,
        col_indices,
        shape=(mesh.n_cells, mesh.n_cells),
    )

    assert np.allclose(assembly0.saturation_excess_rate_m_s, 0.0)
    assert np.allclose(semianalytic_jacobian, dense_jacobian, atol=1.0e-8)


def test_semianalytic_regularized_partition_jacobian_matches_dense_fd_steady(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head = np.asarray([9.95, 10.95], dtype=float)
    recharge_rate = 2.0e-7

    def full_residual_fn(candidate_head: np.ndarray) -> np.ndarray:
        return assemble_steady_residual(
            mesh,
            head_m=candidate_head,
            recharge_rate_m_s=recharge_rate,
        ).residual_m3_s

    assembly0 = assemble_steady_residual(
        mesh,
        head_m=head,
        recharge_rate_m_s=recharge_rate,
    )
    dense_jacobian = build_dense_fd_jacobian(
        full_residual_fn,
        head,
        assembly0.residual_m3_s,
        rel_step=1.0e-7,
    )
    data, row_indices, col_indices = (
        build_sparse_semianalytic_regularized_partition_jacobian_triplets(
            mesh,
            head,
            regularization_radius=0.05,
            surface_input_rate_m_s=recharge_rate,
        )
    )
    semianalytic_jacobian = _triplets_to_dense(
        data,
        row_indices,
        col_indices,
        shape=(mesh.n_cells, mesh.n_cells),
    )

    assert np.any(assembly0.saturation_excess_rate_m_s > 0.0)
    assert np.allclose(semianalytic_jacobian, dense_jacobian, atol=1.0e-8)


def test_semianalytic_regularized_partition_jacobian_matches_dense_fd_transient(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head_prev = np.asarray([9.85, 10.80], dtype=float)
    head = np.asarray([9.95, 10.95], dtype=float)
    recharge_rate = 2.0e-7
    imposed_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    imposed_heads[mesh.boundary_edge_indices_for_side("west_side")] = 10.0
    imposed_heads[mesh.boundary_edge_indices_for_side("east_side")] = 10.8

    def full_residual_fn(candidate_head: np.ndarray) -> np.ndarray:
        return assemble_transient_residual(
            mesh,
            head_m=candidate_head,
            head_prev_m=head_prev,
            dt_seconds=1800.0,
            recharge_rate_m_s=recharge_rate,
            imposed_head_m_by_edge=imposed_heads,
        ).residual_m3_s

    assembly0 = assemble_transient_residual(
        mesh,
        head_m=head,
        head_prev_m=head_prev,
        dt_seconds=1800.0,
        recharge_rate_m_s=recharge_rate,
        imposed_head_m_by_edge=imposed_heads,
    )
    dense_jacobian = build_dense_fd_jacobian(
        full_residual_fn,
        head,
        assembly0.residual_m3_s,
        rel_step=1.0e-7,
    )
    data, row_indices, col_indices = (
        build_sparse_semianalytic_regularized_partition_jacobian_triplets(
            mesh,
            head,
            dt_seconds=1800.0,
            regularization_radius=0.05,
            surface_input_rate_m_s=recharge_rate,
            imposed_head_m_by_edge=imposed_heads,
        )
    )
    semianalytic_jacobian = _triplets_to_dense(
        data,
        row_indices,
        col_indices,
        shape=(mesh.n_cells, mesh.n_cells),
    )

    assert np.any(assembly0.saturation_excess_rate_m_s > 0.0)
    assert np.allclose(semianalytic_jacobian, dense_jacobian, atol=1.0e-8)


def test_boussinesq_mesh_builds_from_gmsh_bundle(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)

    mesh = BoussinesqMesh.from_bundle(bundle)

    assert mesh.n_cells == 2
    assert mesh.n_edges == 5
    assert mesh.n_nodes == 4
    assert int(np.count_nonzero(mesh.interior_edge_mask)) == 1
    assert int(np.count_nonzero(mesh.boundary_edge_mask)) == 4
    assert np.allclose(mesh.hydraulic_conductivity_m_s, [1.0e-5, 2.0e-5])
    assert np.allclose(mesh.storage_coefficient, [0.10, 0.15])
    assert np.all(mesh.edge_distance_m > 0.0)


def test_boussinesq_mesh_projects_cardinal_side_boundaries(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))

    assert mesh.boundary_edge_indices_for_side("south_side").tolist() == [0]
    assert mesh.boundary_edge_indices_for_side("east_side").tolist() == [1]
    assert mesh.boundary_edge_indices_for_side("north_side").tolist() == [3]
    assert mesh.boundary_edge_indices_for_side("west_side").tolist() == [4]


def test_boussinesq_mesh_locates_point_in_triangle(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))

    assert mesh.locate_cell_index_for_point(0.75, 0.25) == 0
    assert mesh.locate_cell_index_for_point(0.25, 0.75) == 1


def test_boussinesq_mesh_exposes_river_edge_indices(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle", river_internal_edge=True)
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))

    assert mesh.river_edge_indices().tolist() == [2]


def test_boussinesq_mesh_rejects_missing_storage_field(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(
        tmp_path / "bundle_missing_storage",
        storage_in_second_cell=False,
    )
    bundle = load_catchment_mesh_bundle(bundle_dir)

    with pytest.raises(ValueError, match="storage_coefficient"):
        BoussinesqMesh.from_bundle(bundle)


def test_regularized_partition_initial_guess_moves_surface_values_to_midpoint(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_partition_initial_guess")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    initial = np.asarray([mesh.z_top_m[0], mesh.z_bottom_m[1]], dtype=float)

    adjusted = interiorize_regularized_partition_initial_guess(mesh, initial)

    expected = 0.5 * (mesh.z_top_m + mesh.z_bottom_m)
    assert np.allclose(adjusted, expected)


def test_regularized_partition_jacobian_shift_decays_with_residual() -> None:
    diagonal = np.asarray([0.0, 2.0e-4, 5.0e-4, 1.0e-3], dtype=float)

    shift_start = regularized_partition_jacobian_shift(
        diagonal,
        residual_norm_inf=1.0,
        initial_residual_norm_inf=1.0,
    )
    shift_late = regularized_partition_jacobian_shift(
        diagonal,
        residual_norm_inf=1.0e-4,
        initial_residual_norm_inf=1.0,
    )

    assert shift_start > shift_late
    assert shift_late >= 1.0e-8


def test_boussinesq_initializes_head_from_flow_initial_conditions(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(FlowConfig.model_validate({"ic": {"type": "top"}}))

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=None,
        model_folder=tmp_path,
        model_name="demo_boussinesq",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.state is not None
    assert np.allclose(model.state.head_m, [10.0, 11.0])
    # Smooth operators introduce O(eps_thickness/2) ≈ 2.5 mm bias at h = z_top.
    assert np.allclose(model.state.saturated_thickness_m, [5.0, 7.0], atol=5.0e-3)
    assert model.has_numerical_solution is False


def test_local_backward_euler_step_conserves_mass_and_relaxes_gradient(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head_prev = np.asarray([9.0, 6.0], dtype=float)
    stored_prev = float(
        np.sum(mesh.cell_area_m2 * mesh.storage_coefficient * head_prev)
    )

    step = solve_backward_euler_step(
        mesh,
        head_prev_m=head_prev,
        dt_seconds=3600.0,
    )

    stored_next = float(
        np.sum(mesh.cell_area_m2 * mesh.storage_coefficient * step.head_m)
    )
    assert step.converged is True
    assert step.iterations >= 1
    assert step.residual_norm_inf <= 1.0e-9
    assert step.head_m[0] < head_prev[0]
    assert step.head_m[1] > head_prev[1]
    assert stored_next <= stored_prev
    assert np.isclose(stored_next, stored_prev, rtol=0.0, atol=2.0e-6)


def test_assembly_with_positive_recharge_balances_by_saturation_excess(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head = np.asarray([11.0, 11.0], dtype=float)

    assembly = assemble_transient_residual(
        mesh,
        head_m=head,
        head_prev_m=head,
        dt_seconds=3600.0,
        recharge_rate_m_s=2.0e-7,
    )

    assert np.allclose(assembly.internal_edge_flux_m3_s, 0.0)
    assert np.all(assembly.saturation_excess_rate_m_s > 0.0)
    # Smooth operators introduce < 1 % bias at full saturation.
    assert np.allclose(assembly.saturation_excess_rate_m_s, 2.0e-7, rtol=0.01)
    assert np.allclose(assembly.residual_m3_s, 0.0, atol=2.0e-9)


def test_local_backward_euler_step_with_side_dirichlet_boundary_injects_water(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head_prev = np.asarray([7.0, 7.0], dtype=float)
    boundary_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    boundary_heads[mesh.boundary_edge_indices_for_side("west_side")] = 10.0

    step = solve_backward_euler_step(
        mesh,
        head_prev_m=head_prev,
        dt_seconds=3600.0,
        imposed_head_m_by_edge=boundary_heads,
    )

    assert step.converged is True
    assert step.assembly.imposed_head_edge_flux_m3_s[4] < 0.0
    assert step.head_m[1] > head_prev[1]
    assert step.head_m[1] > step.head_m[0]


def test_local_backward_euler_step_with_stream_stage_on_internal_river_edge(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle", river_internal_edge=True)
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head_prev = np.asarray([8.0, 8.0], dtype=float)
    imposed_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    imposed_heads[mesh.river_edge_indices()] = 7.0

    step = solve_backward_euler_step(
        mesh,
        head_prev_m=head_prev,
        dt_seconds=3600.0,
        imposed_head_m_by_edge=imposed_heads,
    )

    assert step.converged is True
    assert step.assembly.imposed_head_edge_flux_m3_s[2] > 0.0
    assert np.all(step.head_m < head_prev)


def test_local_backward_euler_step_with_pumping_well_draws_down_target_cell(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head_prev = np.asarray([8.0, 8.0], dtype=float)
    well_flux = np.zeros(mesh.n_cells, dtype=float)
    well_flux[0] = -1.0e-5

    step = solve_backward_euler_step(
        mesh,
        head_prev_m=head_prev,
        dt_seconds=3600.0,
        well_flux_m3_s=well_flux,
    )

    assert step.converged is True
    assert np.isclose(step.assembly.well_flux_m3_s[0], -1.0e-5)
    assert step.head_m[0] < head_prev[0]
    assert step.head_m[0] <= step.head_m[1]


def test_local_backward_euler_step_with_drainage_reduces_surface_overshoot(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head_prev = np.asarray([10.5, 11.5], dtype=float)

    step = solve_backward_euler_step(
        mesh,
        head_prev_m=head_prev,
        dt_seconds=3600.0,
        drainage_conductance_m2_s=1.0e-5,
    )

    assert step.converged is True
    assert np.any(step.assembly.drainage_flux_m3_s > 0.0)
    assert step.head_m[0] < head_prev[0]
    assert step.head_m[1] < head_prev[1]


def test_assembly_steady_state_balances_uniform_fixed_head(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    head = np.full(mesh.n_cells, 8.0, dtype=float)
    imposed_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    imposed_heads[mesh.boundary_edge_indices_for_side("west_side")] = 8.0
    imposed_heads[mesh.boundary_edge_indices_for_side("east_side")] = 8.0

    assembly = assemble_steady_residual(
        mesh,
        head_m=head,
        imposed_head_m_by_edge=imposed_heads,
    )

    # Smooth saturation-excess adds O(eps_qex²) residual at balance_rate = 0.
    assert np.allclose(assembly.residual_m3_s, 0.0, atol=1.0e-11)


def test_assembly_rejects_mixing_imposed_head_edges_and_prescribed_head_cells(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    imposed_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    imposed_heads[mesh.boundary_edge_indices_for_side("west_side")] = 10.0
    prescribed_heads = np.full(mesh.n_cells, np.nan, dtype=float)
    prescribed_heads[0] = 10.0

    with pytest.raises(ValueError, match="mutually exclusive"):
        assemble_steady_residual(
            mesh,
            head_m=np.full(mesh.n_cells, 7.0, dtype=float),
            imposed_head_m_by_edge=imposed_heads,
            prescribed_head_m_by_cell=prescribed_heads,
        )


def test_local_steady_state_with_side_dirichlet_relaxes_between_boundary_heads(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    imposed_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    imposed_heads[mesh.boundary_edge_indices_for_side("west_side")] = 10.0
    imposed_heads[mesh.boundary_edge_indices_for_side("east_side")] = 6.0

    steady = solve_steady_state(
        mesh,
        head_initial_guess_m=np.full(mesh.n_cells, 7.0, dtype=float),
        imposed_head_m_by_edge=imposed_heads,
    )

    assert steady.converged is True
    assert steady.iterations >= 1
    assert steady.residual_norm_inf <= 1.0e-9
    assert steady.head_m[1] > steady.head_m[0]
    assert steady.assembly.imposed_head_edge_flux_m3_s[4] < 0.0
    assert steady.assembly.imposed_head_edge_flux_m3_s[1] > 0.0


def test_scipy_steady_result_reassembles_outputs_on_final_head(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    imposed_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    imposed_heads[mesh.boundary_edge_indices_for_side("west_side")] = 10.0
    imposed_heads[mesh.boundary_edge_indices_for_side("east_side")] = 6.0

    steady = solve_steady_problem_scipy(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=np.full(mesh.n_cells, 7.0, dtype=float),
            imposed_head_m_by_edge=imposed_heads,
        )
    )

    assert steady.converged is True
    rebuilt = assemble_steady_residual(
        mesh,
        head_m=steady.head_m,
        imposed_head_m_by_edge=imposed_heads,
    )
    assert np.allclose(steady.assembly.residual_m3_s, rebuilt.residual_m3_s)
    assert np.allclose(
        steady.assembly.imposed_head_edge_flux_m3_s,
        rebuilt.imposed_head_edge_flux_m3_s,
    )


def test_scipy_sparse_steady_result_reassembles_outputs_on_final_head(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    mesh = BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(bundle_dir))
    imposed_heads = np.full(mesh.n_edges, np.nan, dtype=float)
    imposed_heads[mesh.boundary_edge_indices_for_side("west_side")] = 10.0
    imposed_heads[mesh.boundary_edge_indices_for_side("east_side")] = 6.0

    steady = solve_steady_problem_scipy_sparse(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=np.full(mesh.n_cells, 7.0, dtype=float),
            imposed_head_m_by_edge=imposed_heads,
        )
    )

    assert steady.converged is True
    rebuilt = assemble_steady_residual(
        mesh,
        head_m=steady.head_m,
        imposed_head_m_by_edge=imposed_heads,
    )
    assert np.allclose(steady.assembly.residual_m3_s, rebuilt.residual_m3_s)
    assert np.allclose(
        steady.assembly.imposed_head_edge_flux_m3_s,
        rebuilt.imposed_head_edge_flux_m3_s,
    )


def test_boussinesq_runs_one_transient_period_and_keeps_history(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(FlowConfig.model_validate({"ic": {"type": "top"}}))

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type("TimeGrid", (), {"period_lengths_seconds": (3600.0,)})(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_transient",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.head_history_m is not None
    assert model.state.saturated_thickness_history_m is not None
    assert model.state.head_history_m.shape == (2, 2)
    assert model.state.saturated_thickness_history_m.shape == (2, 2)
    assert len(model.state.nonlinear_iterations) == 1
    assert model.state.nonlinear_iterations[0] >= 1
    assert model.state.converged_by_period == (True,)
    assert model.state.head_m[0] >= 10.0
    assert model.state.head_m[1] < 11.0


def test_boussinesq_runs_one_transient_period_with_scipy_backend(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "runtime_backend": "scipy",
                "ic": {"type": "top"},
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type("TimeGrid", (), {"period_lengths_seconds": (3600.0,)})(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_transient_scipy",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.runtime_summary["runtime_backend"] == "scipy"
    assert model.state.head_history_m is not None
    assert model.state.head_history_m.shape == (2, 2)
    assert model.state.converged_by_period == (True,)


def test_boussinesq_runs_one_transient_period_with_scipy_sparse_backend(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "runtime_backend": "scipy_sparse",
                "ic": {"type": "top"},
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type("TimeGrid", (), {"period_lengths_seconds": (3600.0,)})(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_transient_scipy_sparse",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.runtime_summary["runtime_backend"] == "scipy_sparse"
    assert model.runtime_summary["runtime_linear_system_layout"] == "sparse"
    assert model.state.head_history_m is not None
    assert model.state.head_history_m.shape == (2, 2)
    assert model.state.converged_by_period == (True,)


def test_boussinesq_runs_steady_local_runtime_without_time_grid(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "flow_regime": "steady",
                "ic": {"type": "custom", "value": 7.0},
                "active_bc": ["west_side", "east_side"],
                "bc": {
                    "dirichlet": {
                        "west_side": {"value": 10.0},
                        "east_side": {"value": 6.0},
                    }
                },
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=None,
        model_folder=tmp_path,
        model_name="demo_boussinesq_steady",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.runtime_summary["runtime_backend"] == "local"
    assert model.runtime_summary["steady_mode"] == "nonlinear_local"
    assert model.state.head_history_m is not None
    assert model.state.head_history_m.shape == (1, 2)
    assert model.state.head_m[1] > model.state.head_m[0]
    assert model.state.imposed_head_edge_flux_m3_s is not None
    assert model.state.imposed_head_edge_flux_m3_s[4] < 0.0


def test_boussinesq_post_processing_exports_legacy_and_current_boundary_flux_fields(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "flow_regime": "steady",
                "ic": {"type": "custom", "value": 7.0},
                "active_bc": ["west_side", "east_side"],
                "bc": {
                    "dirichlet": {
                        "west_side": {"value": 10.0},
                        "east_side": {"value": 6.0},
                    }
                },
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=None,
        model_folder=tmp_path,
        model_name="demo_boussinesq_export_contract",
    )

    model.pre_processing()
    assert model.processing(run_model=True) is True
    model.post_processing()

    payload = np.load(model.full_path / "_boussinesq_state_history.npz")

    assert "imposed_head_edge_flux_m3_s" in payload.files
    assert "imposed_head_edge_flux_history_m3_s" in payload.files
    assert "prescribed_head_flux_m3_s" in payload.files
    assert "prescribed_head_flux_history_m3_s" in payload.files
    assert np.allclose(
        payload["imposed_head_edge_flux_m3_s"],
        model.state.imposed_head_edge_flux_m3_s,
    )
    assert payload["imposed_head_edge_flux_history_m3_s"].shape[1] == model.mesh.n_edges


def test_boussinesq_runs_steady_scipy_runtime_without_time_grid(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "flow_regime": "steady",
                "runtime_backend": "scipy",
                "ic": {"type": "custom", "value": 7.0},
                "active_bc": ["west_side", "east_side"],
                "bc": {
                    "dirichlet": {
                        "west_side": {"value": 10.0},
                        "east_side": {"value": 6.0},
                    }
                },
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=None,
        model_folder=tmp_path,
        model_name="demo_boussinesq_scipy_steady",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.runtime_summary["runtime_backend"] == "scipy"
    assert model.runtime_summary["steady_mode"] == "nonlinear_scipy"
    assert model.runtime_summary["runtime_linear_system_layout"] == "dense"
    assert (
        model.runtime_summary["runtime_convergence_policy"]
        == "state_update_inf <= tol_state_update_inf and residual_inf <= tol_residual_inf"
    )
    assert model.runtime_summary["runtime_iteration_counter"] == "function_evaluations"
    assert model.state.head_m[1] > model.state.head_m[0]


def test_boussinesq_runs_steady_scipy_sparse_runtime_without_time_grid(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "flow_regime": "steady",
                "runtime_backend": "scipy_sparse",
                "ic": {"type": "custom", "value": 7.0},
                "active_bc": ["west_side", "east_side"],
                "bc": {
                    "dirichlet": {
                        "west_side": {"value": 10.0},
                        "east_side": {"value": 6.0},
                    }
                },
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=None,
        model_folder=tmp_path,
        model_name="demo_boussinesq_scipy_sparse_steady",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.runtime_summary["runtime_backend"] == "scipy_sparse"
    assert model.runtime_summary["steady_mode"] == "nonlinear_scipy_sparse"
    assert (
        model.runtime_summary["runtime_solver_kind"]
        == "scipy_sparse_newton_line_search_semianalytic_regularized_partition"
    )
    assert model.runtime_summary["runtime_linear_system_layout"] == "sparse"
    assert (
        model.runtime_summary["runtime_convergence_policy"]
        == "residual_inf <= tol_residual_inf"
    )
    assert model.runtime_summary["runtime_iteration_counter"] == "newton_iterations"
    assert model.state.head_m[1] > model.state.head_m[0]


def test_boussinesq_uses_runtime_tolerance_overrides_from_flow(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "flow_regime": "steady",
                "runtime_backend": "scipy_sparse",
                "runtime_max_iterations": 41,
                "runtime_tol_residual_inf": 1.0e-7,
                "runtime_tol_state_update_inf": 1.0e-8,
                "ic": {"type": "custom", "value": 7.0},
                "active_bc": ["west_side", "east_side"],
                "bc": {
                    "dirichlet": {
                        "west_side": {"value": 10.0},
                        "east_side": {"value": 6.0},
                    }
                },
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=None,
        model_folder=tmp_path,
        model_name="demo_boussinesq_runtime_overrides",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.runtime_summary["runtime_backend"] == "scipy_sparse"
    assert model.runtime_summary["runtime_tol_residual_inf"] == pytest.approx(1.0e-7)
    assert model.runtime_summary["runtime_tol_state_update_inf"] == pytest.approx(1.0e-8)


def test_boussinesq_runs_recharge_runtime_and_tracks_saturation_excess(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "ic": {"type": "custom", "value": 11.0},
                "active_sinks_sources": ["recharge"],
                "sinks_sources": {"recharge": {"values": 2.0e-7}},
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type("TimeGrid", (), {"period_lengths_seconds": (3600.0,)})(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_recharge",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.saturation_excess_history_m_s is not None
    assert model.state.saturation_excess_history_m_s.shape == (2, 2)
    assert np.any(model.state.saturation_excess_rate_m_s > 0.0)
    assert np.allclose(model.state.recharge_rate_m_s, 2.0e-7)


def test_post_processing_records_surface_threshold_and_complementarity_summary(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "ic": {"type": "custom", "value": 8.0},
                "runtime_backend": "petsc",
                "surface_interaction_model": "complementarity",
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type(
            "TimeGrid",
            (),
            {"period_lengths_seconds": (3600.0, 3600.0)},
        )(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_surface_summary",
    )
    model.pre_processing()
    assert model.mesh is not None

    head_history_m = np.asarray(
        [
            [9.8, 10.8],
            [10.0, 11.0],
            [9.9, 10.9],
            [10.000000001, 11.0],
        ],
        dtype=float,
    )
    saturation_excess_history_m_s = np.asarray(
        [
            [0.0, 0.0],
            [1.0e-7, 0.0],
            [0.0, 0.0],
            [1.5e-7, -1.0e-13],
        ],
        dtype=float,
    )
    final_head_m = np.asarray(head_history_m[-1], dtype=float)
    final_q_ex_m_s = np.asarray(saturation_excess_history_m_s[-1], dtype=float)
    model.state = BoussinesqState(
        head_m=final_head_m,
        saturated_thickness_m=saturated_thickness_from_head(model.mesh, final_head_m),
        saturation_excess_rate_m_s=final_q_ex_m_s,
        head_history_m=head_history_m,
        saturation_excess_history_m_s=saturation_excess_history_m_s,
        period_lengths_seconds=(3600.0, 3600.0, 3600.0),
        nonlinear_iterations=(2, 3, 4),
        converged_by_period=(True, True, True),
    )
    model.runtime_summary.update(
        {
            "runtime_backend": "petsc",
            "surface_interaction_model_resolved": "complementarity",
        }
    )
    model.has_numerical_solution = True
    model.solve_stage = "solved"

    model.post_processing()

    summary = json.loads(
        (tmp_path / "demo_boussinesq_surface_summary" / "_boussinesq_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["surface_threshold_active_any"] is True
    assert summary["surface_threshold_first_active_step"] == 1
    assert summary["surface_threshold_first_active_day"] == pytest.approx(3600.0 / 86_400.0)
    assert summary["surface_threshold_active_steps"] == 2
    assert summary["surface_threshold_activation_windows"] == 2
    assert summary["surface_threshold_deactivation_windows"] == 1
    assert summary["surface_threshold_state_transitions"] == 3
    assert summary["surface_threshold_peak_active_cells"] == 1
    assert summary["surface_threshold_peak_active_fraction"] == pytest.approx(0.5)
    assert summary["surface_threshold_peak_total_m3_day"] > 0.0
    assert summary["surface_threshold_peak_cell_rate_mm_day"] > 0.0
    assert summary["surface_threshold_peak_head_above_top_m"] == pytest.approx(1.0e-9)
    assert summary["surface_complementarity_min_gap_m"] == pytest.approx(-1.0e-9)
    assert summary["surface_complementarity_min_rate_m_s"] == pytest.approx(-1.0e-13)
    assert summary["surface_complementarity_peak_overlap_m2_s"] == pytest.approx(0.0)
    assert summary["surface_complementarity_final_overlap_m2_s"] == pytest.approx(0.0)


def test_boussinesq_runs_absolute_xy_well_runtime(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "ic": {"type": "custom", "value": 8.0},
                "active_sinks_sources": ["wells"],
                "sinks_sources": {
                    "wells": {
                        "W1": {
                            "location_mode": "absolute_xy",
                            "x": 0.75,
                            "y": 0.25,
                            "flux": -1.0e-5,
                        }
                    }
                },
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type("TimeGrid", (), {"period_lengths_seconds": (3600.0,)})(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_well",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.state is not None
    assert model.state.well_flux_m3_s is not None
    assert np.isclose(model.state.well_flux_m3_s[0], -1.0e-5)
    assert np.isclose(model.state.well_flux_m3_s[1], 0.0)
    assert model.state.head_m[0] < 8.0


def test_boussinesq_runs_stream_boundary_on_river_edges(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle", river_internal_edge=True)
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "ic": {"type": "custom", "value": 8.0},
                "active_bc": ["stream"],
                "bc": {
                    "dirichlet": {
                        "stream": {"value": 7.0},
                    }
                },
            }
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type("TimeGrid", (), {"period_lengths_seconds": (3600.0,)})(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_stream",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.state is not None
    assert model.state.imposed_head_edge_flux_m3_s is not None
    assert model.state.imposed_head_edge_flux_m3_s[2] > 0.0
    assert np.all(model.state.head_m < 8.0)


def test_boussinesq_runs_ocean_boundary_with_period_dependent_support(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "ic": {"type": "custom", "value": 8.0},
                "active_bc": ["ocean"],
                "bc": {
                    "dirichlet": {
                        "ocean": {"value": 10.5},
                    }
                },
            }
        )
    )
    flow.boundary_conditions["ocean"].value = [10.5, 9.5]
    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type(
            "TimeGrid",
            (),
            {"period_lengths_seconds": (3600.0, 3600.0)},
        )(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_ocean",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.state is not None
    assert model.state.head_history_m is not None
    assert model.runtime_summary["active_ocean"] is True
    assert model.state.head_history_m.shape == (3, 2)
    assert model.state.head_history_m[1, 0] > 8.0
    assert np.allclose(model.state.imposed_head_edge_flux_m3_s[[0, 1]], 0.0, atol=1.0e-12)
    assert np.allclose(model.state.imposed_head_edge_flux_m3_s[[3, 4]], 0.0, atol=1.0e-12)


def test_boussinesq_supports_heterogeneous_recharge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    monkeypatch.setattr(
        "hydromodpy.solver.boussinesq.boussinesq.load_planar_mesh",
        lambda path: _build_planar_mesh(),
    )
    flow = Flow(
        _build_flow_config(
            {
                "ic": {"type": "custom", "value": 7.0},
                "active_sinks_sources": ["recharge"],
                "sinks_sources": {"recharge": {"values": 1.0e-7}},
            }
        )
    )
    flow.sinks_sources["recharge"] = FlowRechargeConfig(
        values=0.0,
        heterogeneous_source=LoadResult(fields=[_make_static_recharge_field_record()]),
        interpolation_method="nearest",
    )
    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type("TimeGrid", (), {"period_lengths_seconds": (3600.0,)})(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_heterogeneous_recharge",
    )

    model.pre_processing()
    success = model.processing(run_model=True)

    assert success is True
    assert model.state is not None
    assert np.allclose(model.state.recharge_rate_m_s, [4.0e-7, 2.0e-7])
    assert model.runtime_summary["active_recharge"] is True


def test_boussinesq_rejects_structured_well_addressing_on_triangular_mesh(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    flow = Flow(
        _build_flow_config(
            {
                "ic": {"type": "custom", "value": 8.0},
                "active_sinks_sources": ["wells"],
                "sinks_sources": {
                    "wells": {
                        "W1": {
                            "cell": [0, 0, 0],
                            "flux": -1.0e-5,
                        }
                    }
                },
            }
        )
    )
    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=type("TimeGrid", (), {"period_lengths_seconds": (3600.0,)})(),
        model_folder=tmp_path,
        model_name="demo_boussinesq_bad_well",
    )

    model.pre_processing()

    with pytest.raises(NotImplementedError, match="coordinate-based wells"):
        model.processing(run_model=True)
