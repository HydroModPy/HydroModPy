from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    accumulate_internal_flux_residual,
    boundary_head_edge_flux_from_head,
    internal_edge_flux_from_head,
    resolve_boundary_head_inputs,
)
from hydromodpy.solver.boussinesq.assembly.residuals import (
    assemble_transient_residual_with_saturation_excess_generic,
)
from hydromodpy.solver.boussinesq.assembly.surface import (
    regularized_partition_surface_rate_from_balance,
)
from hydromodpy.solver.boussinesq.jacobian.operator_triplets import (
    build_sparse_semianalytic_triplets,
)
from hydromodpy.solver.boussinesq.jacobian.partition_triplets import (
    build_sparse_semianalytic_partition_saturation_triplets,
)


@dataclass
class _MiniMesh:
    cell_area_m2: np.ndarray
    z_top_m: np.ndarray
    z_bottom_m: np.ndarray
    hydraulic_conductivity_m_s: np.ndarray
    storage_coefficient: np.ndarray
    edge_ids: np.ndarray
    edge_cell_a: np.ndarray
    edge_cell_b: np.ndarray
    edge_length_m: np.ndarray
    edge_distance_m: np.ndarray
    edge_midpoint_distance_to_cell_a_m: np.ndarray
    edge_midpoint_distance_to_cell_b_m: np.ndarray

    @property
    def n_cells(self) -> int:
        return int(self.cell_area_m2.size)

    @property
    def n_edges(self) -> int:
        return int(self.edge_ids.size)


def _build_mesh() -> _MiniMesh:
    return _MiniMesh(
        cell_area_m2=np.asarray([1.0, 1.0], dtype=float),
        z_top_m=np.asarray([2.0, 2.0], dtype=float),
        z_bottom_m=np.asarray([0.0, 0.0], dtype=float),
        hydraulic_conductivity_m_s=np.asarray([1.0, 1.0], dtype=float),
        storage_coefficient=np.asarray([0.2, 0.3], dtype=float),
        edge_ids=np.asarray([0], dtype=int),
        edge_cell_a=np.asarray([0], dtype=int),
        edge_cell_b=np.asarray([1], dtype=int),
        edge_length_m=np.asarray([1.0], dtype=float),
        edge_distance_m=np.asarray([1.0], dtype=float),
        edge_midpoint_distance_to_cell_a_m=np.asarray([0.5], dtype=float),
        edge_midpoint_distance_to_cell_b_m=np.asarray([0.5], dtype=float),
    )


def _build_single_cell_mesh() -> _MiniMesh:
    return _MiniMesh(
        cell_area_m2=np.asarray([1.0], dtype=float),
        z_top_m=np.asarray([2.0], dtype=float),
        z_bottom_m=np.asarray([0.0], dtype=float),
        hydraulic_conductivity_m_s=np.asarray([1.0], dtype=float),
        storage_coefficient=np.asarray([0.2], dtype=float),
        edge_ids=np.asarray([], dtype=int),
        edge_cell_a=np.asarray([], dtype=int),
        edge_cell_b=np.asarray([], dtype=int),
        edge_length_m=np.asarray([], dtype=float),
        edge_distance_m=np.asarray([], dtype=float),
        edge_midpoint_distance_to_cell_a_m=np.asarray([], dtype=float),
        edge_midpoint_distance_to_cell_b_m=np.asarray([], dtype=float),
    )


def _build_mesh_with_boundary_edge() -> _MiniMesh:
    return _MiniMesh(
        cell_area_m2=np.asarray([1.0, 1.0], dtype=float),
        z_top_m=np.asarray([2.0, 2.0], dtype=float),
        z_bottom_m=np.asarray([0.0, 0.0], dtype=float),
        hydraulic_conductivity_m_s=np.asarray([1.0, 1.0], dtype=float),
        storage_coefficient=np.asarray([0.2, 0.3], dtype=float),
        edge_ids=np.asarray([0, 1], dtype=int),
        edge_cell_a=np.asarray([0, 0], dtype=int),
        edge_cell_b=np.asarray([1, -1], dtype=int),
        edge_length_m=np.asarray([1.0, 1.0], dtype=float),
        edge_distance_m=np.asarray([1.0, 0.5], dtype=float),
        edge_midpoint_distance_to_cell_a_m=np.asarray([0.5, 0.5], dtype=float),
        edge_midpoint_distance_to_cell_b_m=np.asarray([0.5, np.nan], dtype=float),
    )


def _dense_from_triplets(
    mesh: _MiniMesh,
    triplets: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> np.ndarray:
    data, rows, cols = triplets
    dense = np.zeros((mesh.n_cells, mesh.n_cells), dtype=float)
    if data.size != 0:
        np.add.at(dense, (rows, cols), data)
    return dense


def _surface_residual_contribution(
    mesh: _MiniMesh,
    head_m: np.ndarray,
    *,
    regularization_radius: float,
    surface_input_rate_m_s: np.ndarray | float | None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
) -> np.ndarray:
    boundary_inputs = resolve_boundary_head_inputs(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    head = boundary_inputs.head_m
    boundary_head = boundary_inputs.boundary_head_m_by_edge

    internal_flux = internal_edge_flux_from_head(mesh, head)
    internal_residual = accumulate_internal_flux_residual(mesh, internal_flux)
    if np.any(np.isfinite(boundary_head)):
        _, boundary_residual = boundary_head_edge_flux_from_head(
            mesh,
            head,
            boundary_head_m_by_edge=boundary_head,
        )
    else:
        boundary_residual = np.zeros(mesh.n_cells, dtype=float)

    surface_rate = regularized_partition_surface_rate_from_balance(
        mesh,
        head,
        lateral_flux_residual_m3_s=internal_residual + boundary_residual,
        surface_input_rate_m_s=surface_input_rate_m_s,
        regularization_radius=regularization_radius,
    )
    return np.asarray(mesh.cell_area_m2, dtype=float) * surface_rate


def _transient_residual(
    mesh: _MiniMesh,
    head_m: np.ndarray,
    *,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> np.ndarray:
    assembly = assemble_transient_residual_with_saturation_excess_generic(
        mesh,
        head_m=head_m,
        head_prev_m=head_prev_m,
        dt_seconds=dt_seconds,
        saturation_excess_rate_m_s=0.0,
        recharge_rate_m_s=0.0,
        well_flux_m3_s=0.0,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=0.25,
    )
    return np.asarray(assembly.residual_m3_s, dtype=float)


def test_boussinesq_package_keeps_mesh_import_lightweight() -> None:
    import hydromodpy.solver.boussinesq as package

    assert package.BoussinesqMesh.__name__ == "BoussinesqMesh"


def test_partition_triplets_match_finite_difference_surface_contribution() -> None:
    mesh = _build_mesh()
    head = np.asarray([1.2, 0.8], dtype=float)
    regularization_radius = 0.25
    surface_input_rate_m_s = np.asarray([1.0, 1.0], dtype=float)

    dense = _dense_from_triplets(
        mesh,
        build_sparse_semianalytic_partition_saturation_triplets(
            mesh,
            head,
            regularization_radius=regularization_radius,
            surface_input_rate_m_s=surface_input_rate_m_s,
            boundary_head_m_by_edge=None,
            prescribed_head_m_by_cell=None,
        ),
    )

    step = 1.0e-6
    fd = np.zeros_like(dense)
    for col in range(mesh.n_cells):
        direction = np.zeros(mesh.n_cells, dtype=float)
        direction[col] = step
        plus = _surface_residual_contribution(
            mesh,
            head + direction,
            regularization_radius=regularization_radius,
            surface_input_rate_m_s=surface_input_rate_m_s,
        )
        minus = _surface_residual_contribution(
            mesh,
            head - direction,
            regularization_radius=regularization_radius,
            surface_input_rate_m_s=surface_input_rate_m_s,
        )
        fd[:, col] = (plus - minus) / (2.0 * step)

    np.testing.assert_allclose(dense, fd, rtol=1.0e-5, atol=1.0e-7)


def test_partition_triplets_drop_out_when_surface_ramp_is_inactive() -> None:
    mesh = _build_mesh()
    data, rows, cols = build_sparse_semianalytic_partition_saturation_triplets(
        mesh,
        np.asarray([1.0, 1.0], dtype=float),
        regularization_radius=0.25,
        surface_input_rate_m_s=0.0,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=None,
    )

    assert data.size == 0
    assert rows.size == 0
    assert cols.size == 0


def test_partition_triplets_zero_prescribed_rows_and_columns() -> None:
    mesh = _build_mesh()
    dense = _dense_from_triplets(
        mesh,
        build_sparse_semianalytic_partition_saturation_triplets(
            mesh,
            np.asarray([1.2, 0.8], dtype=float),
            regularization_radius=0.25,
            surface_input_rate_m_s=1.0,
            boundary_head_m_by_edge=None,
            prescribed_head_m_by_cell=np.asarray([np.nan, 0.5], dtype=float),
        ),
    )

    np.testing.assert_allclose(dense[1, :], 0.0, atol=0.0)
    np.testing.assert_allclose(dense[:, 1], 0.0, atol=0.0)


def test_operator_triplets_match_finite_difference_transient_residual() -> None:
    mesh = _build_mesh_with_boundary_edge()
    head = np.asarray([1.2, 0.8], dtype=float)
    head_prev = np.asarray([1.1, 0.7], dtype=float)
    boundary_head = np.asarray([np.nan, 1.6], dtype=float)
    drainage_conductance = np.asarray([0.5, 0.2], dtype=float)
    dt_seconds = 10.0

    dense = _dense_from_triplets(
        mesh,
        build_sparse_semianalytic_triplets(
            mesh,
            head,
            dt_seconds=dt_seconds,
            boundary_head_m_by_edge=boundary_head,
            prescribed_head_m_by_cell=None,
            drainage_conductance_m2_s=drainage_conductance,
            include_storage=True,
            include_internal_flux=True,
            include_boundary_head_flux=True,
            include_drainage=True,
            include_prescribed_identity=False,
        ),
    )

    step = 1.0e-6
    fd = np.zeros_like(dense)
    for col in range(mesh.n_cells):
        direction = np.zeros(mesh.n_cells, dtype=float)
        direction[col] = step
        plus = _transient_residual(
            mesh,
            head + direction,
            head_prev_m=head_prev,
            dt_seconds=dt_seconds,
            boundary_head_m_by_edge=boundary_head,
            drainage_conductance_m2_s=drainage_conductance,
        )
        minus = _transient_residual(
            mesh,
            head - direction,
            head_prev_m=head_prev,
            dt_seconds=dt_seconds,
            boundary_head_m_by_edge=boundary_head,
            drainage_conductance_m2_s=drainage_conductance,
        )
        fd[:, col] = (plus - minus) / (2.0 * step)

    np.testing.assert_allclose(dense, fd, rtol=1.0e-5, atol=1.0e-7)


def test_transient_storage_uses_lower_bounded_saturated_thickness() -> None:
    mesh = _build_single_cell_mesh()
    dt_seconds = 10.0

    residual = _transient_residual(
        mesh,
        np.asarray([-0.5], dtype=float),
        head_prev_m=np.asarray([0.5], dtype=float),
        dt_seconds=dt_seconds,
    )
    np.testing.assert_allclose(residual, np.asarray([-0.01], dtype=float))

    residual = _transient_residual(
        mesh,
        np.asarray([-0.5], dtype=float),
        head_prev_m=np.asarray([-0.2], dtype=float),
        dt_seconds=dt_seconds,
    )
    np.testing.assert_allclose(residual, np.asarray([0.0], dtype=float))

    residual = _transient_residual(
        mesh,
        np.asarray([3.0], dtype=float),
        head_prev_m=np.asarray([1.5], dtype=float),
        dt_seconds=dt_seconds,
    )
    np.testing.assert_allclose(residual, np.asarray([0.03], dtype=float))


def test_operator_storage_diagonal_keeps_memory_above_surface() -> None:
    mesh = _build_single_cell_mesh()
    dt_seconds = 10.0

    def _storage_jacobian(head_value: float) -> np.ndarray:
        return _dense_from_triplets(
            mesh,
            build_sparse_semianalytic_triplets(
                mesh,
                np.asarray([head_value], dtype=float),
                dt_seconds=dt_seconds,
                boundary_head_m_by_edge=None,
                prescribed_head_m_by_cell=None,
                drainage_conductance_m2_s=None,
                include_storage=True,
                include_internal_flux=False,
                include_boundary_head_flux=False,
                include_drainage=False,
                include_prescribed_identity=False,
            ),
        )

    np.testing.assert_allclose(_storage_jacobian(1.0), np.asarray([[0.02]], dtype=float))
    np.testing.assert_allclose(_storage_jacobian(-0.5), np.asarray([[0.0]], dtype=float))
    np.testing.assert_allclose(_storage_jacobian(3.0), np.asarray([[0.02]], dtype=float))


def test_operator_triplets_match_finite_difference_with_prescribed_identity() -> None:
    mesh = _build_mesh()
    head = np.asarray([1.2, 0.8], dtype=float)
    head_prev = np.asarray([1.1, 0.6], dtype=float)
    prescribed = np.asarray([np.nan, 0.5], dtype=float)
    dt_seconds = 10.0

    dense = _dense_from_triplets(
        mesh,
        build_sparse_semianalytic_triplets(
            mesh,
            head,
            dt_seconds=dt_seconds,
            boundary_head_m_by_edge=None,
            prescribed_head_m_by_cell=prescribed,
            drainage_conductance_m2_s=None,
            include_storage=True,
            include_internal_flux=True,
            include_boundary_head_flux=True,
            include_drainage=True,
            include_prescribed_identity=True,
        ),
    )

    step = 1.0e-6
    fd = np.zeros_like(dense)
    for col in range(mesh.n_cells):
        direction = np.zeros(mesh.n_cells, dtype=float)
        direction[col] = step
        plus = _transient_residual(
            mesh,
            head + direction,
            head_prev_m=head_prev,
            dt_seconds=dt_seconds,
            prescribed_head_m_by_cell=prescribed,
        )
        minus = _transient_residual(
            mesh,
            head - direction,
            head_prev_m=head_prev,
            dt_seconds=dt_seconds,
            prescribed_head_m_by_cell=prescribed,
        )
        fd[:, col] = (plus - minus) / (2.0 * step)

    np.testing.assert_allclose(dense, fd, rtol=1.0e-5, atol=1.0e-7)
