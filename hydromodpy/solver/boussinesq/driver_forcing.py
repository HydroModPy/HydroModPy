"""Shared forcing/boundary preparation for Boussinesq driver helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from hydromodpy.solver.boussinesq.boussinesq import Boussinesq


@dataclass(frozen=True)
class ResolvedBoundaryForcing:
    """Boundary-support series reused by steady and transient driver helpers."""

    ocean_series_m: np.ndarray | None
    dirichlet_supports_by_period: tuple[tuple[object, ...], ...]
    prescribed_heads_by_period: tuple[np.ndarray, ...]
    boundary_heads_by_period: tuple[np.ndarray, ...]
    ocean_supported_cell_masks: tuple[np.ndarray, ...]
    drainage_conductance_series_m2_s: np.ndarray


def resolve_boundary_forcing_by_period(
    solver: "Boussinesq",
    *,
    nper: int,
) -> ResolvedBoundaryForcing:
    """Resolve one reusable boundary-forcing bundle over all periods."""
    ocean_series_m = solver._resolve_ocean_series(nper)
    dirichlet_supports_by_period = solver._resolved_dirichlet_supports_by_period(
        nper,
        ocean_series_m=ocean_series_m,
    )
    prescribed_heads_by_period = tuple(
        np.asarray(
            solver._project_dirichlet_supports_to_cells(period_supports),
            dtype=float,
        )
        for period_supports in dirichlet_supports_by_period
    )
    boundary_heads_by_period = tuple(
        np.asarray(
            solver._project_dirichlet_supports_to_edges(period_supports),
            dtype=float,
        )
        for period_supports in dirichlet_supports_by_period
    )
    ocean_supported_cell_masks = tuple(
        np.asarray(mask, dtype=bool)
        for mask in solver._ocean_supported_cell_masks_by_period(
            ocean_series_m,
            nper=nper,
        )
    )
    drainage_conductance_series_m2_s = np.asarray(
        solver._resolve_drainage_conductance_series(nper),
        dtype=float,
    )
    return ResolvedBoundaryForcing(
        ocean_series_m=ocean_series_m,
        dirichlet_supports_by_period=tuple(
            tuple(period_supports) for period_supports in dirichlet_supports_by_period
        ),
        prescribed_heads_by_period=prescribed_heads_by_period,
        boundary_heads_by_period=boundary_heads_by_period,
        ocean_supported_cell_masks=ocean_supported_cell_masks,
        drainage_conductance_series_m2_s=drainage_conductance_series_m2_s,
    )


def apply_ocean_drainage_mask(
    *,
    n_cells: int,
    drainage_value_m2_s: float,
    ocean_supported_cell_mask: np.ndarray,
) -> np.ndarray | float:
    """Return drainage conductance with ocean-supported cells muted."""
    mask = np.asarray(ocean_supported_cell_mask, dtype=bool)
    drainage_value = float(drainage_value_m2_s)
    if np.any(mask) and drainage_value != 0.0:
        drainage_conductance = np.full(
            int(n_cells),
            drainage_value,
            dtype=float,
        )
        drainage_conductance[mask] = 0.0
        return drainage_conductance
    return drainage_value


__all__ = [
    "ResolvedBoundaryForcing",
    "apply_ocean_drainage_mask",
    "resolve_boundary_forcing_by_period",
]
