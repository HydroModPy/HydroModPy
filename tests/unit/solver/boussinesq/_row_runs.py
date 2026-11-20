"""A row of cells and a fixed forcing, shared by the Boussinesq run tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.solver.boussinesq.drivers.forcing import ResolvedRuntimeForcing
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from tests._helpers.boussinesq_cell_meshes import placeholder_cell_mesh

DAY_S = 86400.0
N_CELLS = 6
OUTLET_M = 20.0


def row_mesh(n_cells: int = N_CELLS) -> BoussinesqMesh:
    """Return a row of 10 m square cells, 50 m thick, joined by their sides."""
    n_edges = n_cells - 1
    x = 10.0 * np.arange(n_cells + 1, dtype=float)
    return BoussinesqMesh(
        bundle_dir=Path("."),
        cell_ids=np.arange(n_cells),
        node_ids=np.arange(n_cells + 1),
        node_x_m=x,
        node_y_m=np.zeros(n_cells + 1),
        cell_node_ids=tuple((i, i + 1, i) for i in range(n_cells)),
        cell_centroid_x_m=0.5 * (x[:-1] + x[1:]),
        cell_centroid_y_m=np.zeros(n_cells),
        cell_area_m2=np.full(n_cells, 100.0),
        z_top_m=np.full(n_cells, 50.0),
        z_bottom_m=np.zeros(n_cells),
        hydraulic_conductivity_m_s=np.full(n_cells, 1.0e-4),
        storage_coefficient=np.full(n_cells, 0.1),
        edge_ids=np.arange(n_edges),
        edge_node_a=np.arange(1, n_cells),
        edge_node_b=np.arange(1, n_cells),
        edge_cell_a=np.arange(n_edges),
        edge_cell_b=np.arange(1, n_cells),
        edge_length_m=np.full(n_edges, 10.0),
        edge_distance_m=np.full(n_edges, 10.0),
        edge_midpoint_distance_to_cell_a_m=np.full(n_edges, 5.0),
        edge_midpoint_distance_to_cell_b_m=np.full(n_edges, 5.0),
        edge_midpoint_x_m=x[1:-1].copy(),
        edge_midpoint_y_m=np.zeros(n_edges),
        edge_kind=tuple("internal" for _ in range(n_edges)),
        edge_is_river=np.zeros(n_edges, dtype=bool),
        cell_index_by_id={i: i for i in range(n_cells)},
        node_index_by_id={i: i for i in range(n_cells + 1)},
        cell_mesh=placeholder_cell_mesh(n_cells),
    )


def fixed_forcing(rates: tuple[float, ...]):
    """Return a forcing resolver: the first cell held at the outlet head, recharge."""

    def resolve(solver, *, nper: int) -> ResolvedRuntimeForcing:
        mesh = solver.mesh
        held = np.full(mesh.n_cells, np.nan)
        held[0] = OUTLET_M
        return ResolvedRuntimeForcing(
            recharge_series_m_s=tuple(float(rate) for rate in rates[:nper]),
            active_recharge=True,
            well_flux_by_period_m3_s=np.zeros((nper, mesh.n_cells)),
            ocean_series_m=None,
            dirichlet_supports_by_period=tuple(() for _ in range(nper)),
            prescribed_heads_by_period=tuple(held.copy() for _ in range(nper)),
            boundary_heads_by_period=tuple(np.full(mesh.n_edges, np.nan) for _ in range(nper)),
            ocean_supported_cell_masks=tuple(
                np.zeros(mesh.n_cells, dtype=bool) for _ in range(nper)
            ),
            drainage_conductance_series_m2_s=np.zeros(nper),
        )

    return resolve
