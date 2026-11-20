"""The solver grid of a domain, built in the two steps a run takes: the column, then the layers."""

from __future__ import annotations

import numpy as np

from hydromodpy.model.domain.cell_column import modflow_column
from hydromodpy.solver.modflow_grid.discretization_spatial import (
    SolverGridContext,
    build_spatial_discretization,
)


def discretize(
    *,
    domain,
    vertical_config,
    cell_mesh,
    sgrid_config=None,
    channel_mask: np.ndarray | None = None,
) -> SolverGridContext:
    """The column ``prepare_solver`` builds, then the layers the solver adds."""
    column = modflow_column(
        cell_mesh=cell_mesh,
        domain=domain,
        top_sampling=None if sgrid_config is None else sgrid_config.top_sampling,
        channel_mask=channel_mask,
    )
    return build_spatial_discretization(
        domain=domain, vertical_config=vertical_config, cell_mesh=cell_mesh, column=column
    )
