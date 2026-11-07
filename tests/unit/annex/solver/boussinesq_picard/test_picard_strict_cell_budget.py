"""The strict Picard residual gives nothing to a cell with an imposed head.

MODFLOW applies no recharge, no well and no drain on a constant-head cell.
The strict residual of the Picard initializer follows the same convention
as the canonical residual of the wheel.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy_annex.solver.boussinesq_picard.picard import assemble_strict_steady_residual
from tests._helpers.boussinesq_mesh_doubles import _MiniMesh

RECHARGE_M_S = 5.0e-3 / 86400.0
WELL_M3_S = -2.0e-4
DRAIN_M2_S = 1.0e-3


def _strip(n_cells: int, *, outlet_top_m: float = 50.0) -> _MiniMesh:
    """Return a row of 10 m square cells, 50 m thick, joined by their sides."""
    n_edges = n_cells - 1
    z_top = np.full(n_cells, 50.0)
    z_top[0] = outlet_top_m
    return _MiniMesh(
        cell_area_m2=np.full(n_cells, 100.0),
        z_top_m=z_top,
        z_bottom_m=np.zeros(n_cells),
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


def test_strict_steady_residual_gives_nothing_to_a_cell_with_an_imposed_head() -> None:
    # The held head stands 1 m above the ground of its cell, under a well.
    mesh = _strip(3, outlet_top_m=19.0)
    head = np.asarray([20.0, 21.0, 21.5])
    prescribed = np.full(3, np.nan)
    prescribed[0] = 20.0
    wells = np.asarray([WELL_M3_S, 0.0, WELL_M3_S])

    assembly = assemble_strict_steady_residual(
        mesh,
        head,
        recharge_rate_m_s=RECHARGE_M_S,
        well_flux_m3_s=wells,
        prescribed_head_m_by_cell=prescribed,
        drainage_conductance_m2_s=DRAIN_M2_S,
    )

    np.testing.assert_allclose(assembly.recharge_rate_m_s, [0.0, RECHARGE_M_S, RECHARGE_M_S])
    np.testing.assert_allclose(assembly.well_flux_m3_s, [0.0, 0.0, WELL_M3_S])
    np.testing.assert_allclose(assembly.drainage_flux_m3_s, 0.0)
    assert assembly.prescribed_head_flux_m3_s[0] == pytest.approx(
        -assembly.internal_edge_flux_m3_s[0]
    )
