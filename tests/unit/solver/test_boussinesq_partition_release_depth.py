"""The regularized partition releases water by the depth of the water table in metres."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.flow_runtime_config import DEFAULT_PARTITION_RELEASE_DEPTH_M
from hydromodpy.solver.boussinesq.assembly.residual_facade import (
    assemble_steady_residual,
)
from hydromodpy.solver.boussinesq.assembly.surface import (
    partition_release_share,
    partition_vertical_supply_rate_m_s,
    regularized_partition_surface_rate_from_balance,
)
from hydromodpy.solver.boussinesq.jacobian.partition_triplets import (
    build_sparse_semianalytic_partition_saturation_triplets,
)
from hydromodpy.solver.boussinesq.runtimes.local import solve_backward_euler_step
from hydromodpy.solver.boussinesq.solver_contract import build_runtime_options
from tests._helpers.mesh_doubles import _MiniMesh

DEPTH_M = DEFAULT_PARTITION_RELEASE_DEPTH_M


def _strip(n_cells: int, *, z_top_m: float, z_bottom_m: float = 0.0) -> _MiniMesh:
    """Return a row of 10 m square cells joined by their sides."""
    n_edges = n_cells - 1
    return _MiniMesh(
        cell_area_m2=np.full(n_cells, 100.0),
        z_top_m=np.full(n_cells, z_top_m),
        z_bottom_m=np.full(n_cells, z_bottom_m),
        hydraulic_conductivity_m_s=np.full(n_cells, 1.0e-4),
        storage_coefficient=np.full(n_cells, 0.1),
        edge_ids=np.arange(n_edges),
        edge_cell_a=np.arange(n_edges),
        edge_cell_b=np.arange(1, n_cells),
        edge_length_m=np.full(n_edges, 10.0),
        edge_distance_m=np.full(n_edges, 10.0),
        edge_midpoint_distance_to_cell_a_m=np.full(n_edges, 5.0),
        edge_midpoint_distance_to_cell_b_m=np.full(n_edges, 5.0),
    )


def test_default_depth_scale_is_a_flow_field_in_metres() -> None:
    assert FlowConfig().partition_release_depth_m == DEPTH_M == 0.05
    assert (
        build_runtime_options(FlowConfig(partition_release_depth_m=0.02)).regularization_radius
        == 0.02
    )
    with pytest.raises(ValueError):
        FlowConfig(partition_release_depth_m=0.0)


def test_release_share_follows_the_depth_below_the_surface_not_the_thickness() -> None:
    thin = _MiniMesh(z_top_m=np.full(4, 10.0), z_bottom_m=np.zeros(4), cell_area_m2=np.ones(4))
    thick = _MiniMesh(z_top_m=np.full(4, 1000.0), z_bottom_m=np.zeros(4), cell_area_m2=np.ones(4))
    depths = np.asarray([0.0, DEPTH_M, 1.0, 9.0])
    share_thin, _ = partition_release_share(thin, 10.0 - depths, regularization_radius=DEPTH_M)
    share_thick, _ = partition_release_share(thick, 1000.0 - depths, regularization_radius=DEPTH_M)

    np.testing.assert_allclose(share_thin, share_thick, rtol=1e-12, atol=0.0)
    np.testing.assert_allclose(share_thin[:2], [1.0, np.exp(-1.0)], rtol=1e-12)
    assert share_thin[2] < 1e-6
    assert share_thin[3] < 1e-30


def test_release_share_derivative_matches_finite_differences() -> None:
    mesh = _MiniMesh(z_top_m=np.full(3, 5.0), z_bottom_m=np.zeros(3), cell_area_m2=np.ones(3))
    head = np.asarray([4.99, 4.9, 4.5])
    share, dshare_dh = partition_release_share(mesh, head, regularization_radius=DEPTH_M)
    step = 1e-7
    shifted, _ = partition_release_share(mesh, head + step, regularization_radius=DEPTH_M)

    np.testing.assert_allclose(dshare_dh, (shifted - share) / step, rtol=1e-5)


def test_pumped_cell_keeps_the_inflow_its_well_takes() -> None:
    mesh = _strip(2, z_top_m=10.0)
    head = np.asarray([9.99, 9.98])
    lateral = np.asarray([2.0e-5, -2.0e-5])  # cell 1 receives 2e-5 m3/s from cell 0
    without_well = regularized_partition_surface_rate_from_balance(
        mesh,
        head,
        lateral_flux_residual_m3_s=lateral,
        surface_input_rate_m_s=0.0,
        regularization_radius=DEPTH_M,
    )
    with_well = regularized_partition_surface_rate_from_balance(
        mesh,
        head,
        lateral_flux_residual_m3_s=lateral,
        surface_input_rate_m_s=partition_vertical_supply_rate_m_s(
            mesh, recharge_rate_m_s=0.0, well_flux_m3_s=np.asarray([0.0, -2.0e-5])
        ),
        regularization_radius=DEPTH_M,
    )

    assert without_well[1] == pytest.approx(np.exp(-0.02 / DEPTH_M) * 2.0e-7)
    assert with_well[1] == 0.0


def test_negative_recharge_reduces_the_supply_of_a_full_cell() -> None:
    mesh = _strip(1, z_top_m=10.0)
    release = regularized_partition_surface_rate_from_balance(
        mesh,
        np.asarray([10.0]),
        lateral_flux_residual_m3_s=np.asarray([-3.0e-6]),
        surface_input_rate_m_s=partition_vertical_supply_rate_m_s(
            mesh, recharge_rate_m_s=-1.0e-8, well_flux_m3_s=None
        ),
        regularization_radius=DEPTH_M,
    )

    np.testing.assert_allclose(release, [3.0e-8 - 1.0e-8], rtol=1e-12)


def test_cell_with_a_prescribed_head_releases_nothing() -> None:
    # The held cell sits 2 cm under the ground, where a free cell would release
    # two thirds of what it receives. It takes no recharge, so what it receives
    # is the inflow from its free neighbour, and all of it goes to the boundary.
    mesh = _strip(3, z_top_m=5.0)
    prescribed = np.asarray([np.nan, np.nan, 4.98])
    assembly = assemble_steady_residual(
        mesh,
        head_m=np.asarray([5.0, 5.0, 4.98]),
        recharge_rate_m_s=1.0e-8,
        prescribed_head_m_by_cell=prescribed,
        regularization_radius=DEPTH_M,
    )

    inflow_m3_s = assembly.internal_edge_flux_m3_s[1]
    assert inflow_m3_s > 0.0
    assert assembly.saturation_excess_rate_m_s[2] == 0.0
    assert assembly.prescribed_head_flux_m3_s[2] == pytest.approx(inflow_m3_s)


def test_partition_triplets_match_finite_differences_with_wells_and_negative_recharge() -> None:
    mesh = _strip(3, z_top_m=5.0)
    head = np.asarray([4.97, 4.95, 4.9])
    supply = partition_vertical_supply_rate_m_s(
        mesh,
        recharge_rate_m_s=np.asarray([2.0e-6, -1.0e-7, 1.0e-6]),
        well_flux_m3_s=np.asarray([0.0, 5.0e-5, -1.0e-5]),
    )

    def release_m3_s(candidate: np.ndarray) -> np.ndarray:
        assembly = assemble_steady_residual(
            mesh,
            head_m=candidate,
            recharge_rate_m_s=np.asarray([2.0e-6, -1.0e-7, 1.0e-6]),
            well_flux_m3_s=np.asarray([0.0, 5.0e-5, -1.0e-5]),
            regularization_radius=DEPTH_M,
        )
        return mesh.cell_area_m2 * assembly.saturation_excess_rate_m_s

    data, rows, cols = build_sparse_semianalytic_partition_saturation_triplets(
        mesh,
        head,
        regularization_radius=DEPTH_M,
        surface_input_rate_m_s=supply,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=None,
    )
    analytic = np.zeros((3, 3))
    np.add.at(analytic, (rows, cols), data)
    step = 1e-7
    base = release_m3_s(head)
    numeric = np.column_stack(
        [(release_m3_s(head + step * np.eye(3)[j]) - base) / step for j in range(3)]
    )

    assert np.all(base > 0.0)
    np.testing.assert_allclose(analytic, numeric, rtol=1e-4, atol=1e-12)


def test_recharge_on_a_water_table_far_below_the_ground_is_all_stored() -> None:
    mesh = _strip(5, z_top_m=60.0)
    head0 = np.full(5, 50.0)
    recharge = np.asarray([0.0, 0.0, 2.0e-7, 0.0, 0.0])
    dt = 86400.0
    result = solve_backward_euler_step(
        mesh,
        head_prev_m=head0,
        dt_seconds=dt,
        recharge_rate_m_s=recharge,
        regularization_radius=DEPTH_M,
        tol_residual_inf=1e-14,
    )

    stored = np.sum(mesh.storage_coefficient * mesh.cell_area_m2 * (result.head_m - head0))
    assert result.converged
    assert stored == pytest.approx(np.sum(recharge * mesh.cell_area_m2) * dt, rel=1e-9)
    assert np.max(result.assembly.saturation_excess_rate_m_s) < 1e-60
