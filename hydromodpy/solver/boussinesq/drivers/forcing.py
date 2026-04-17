"""Shared forcing/boundary preparation for Boussinesq driver helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from hydromodpy.solver.boussinesq.forcing_resolution import BoussinesqForcingResolver


class BoussinesqForcingSolver(Protocol):
    """Minimal solver contract required to build one forcing resolver."""

    def _forcing_resolver(self) -> BoussinesqForcingResolver: ...


@dataclass(frozen=True)
class ResolvedRuntimeForcing:
    """Runtime-ready forcing bundle reused by steady and transient helpers."""

    recharge_series_m_s: tuple[float | np.ndarray, ...]
    active_recharge: bool
    well_flux_by_period_m3_s: np.ndarray
    ocean_series_m: np.ndarray | None
    dirichlet_supports_by_period: tuple[tuple[object, ...], ...]
    prescribed_heads_by_period: tuple[np.ndarray, ...]
    boundary_heads_by_period: tuple[np.ndarray, ...]
    ocean_supported_cell_masks: tuple[np.ndarray, ...]
    drainage_conductance_series_m2_s: np.ndarray


def _forcing_resolver_for(solver: BoussinesqForcingSolver) -> BoussinesqForcingResolver:
    """Build one forcing resolver from the current solver state."""
    return solver._forcing_resolver()


def resolve_runtime_forcing_by_period(
    solver: BoussinesqForcingSolver,
    *,
    nper: int,
) -> ResolvedRuntimeForcing:
    """Resolve one reusable forcing bundle over all periods."""
    resolver = _forcing_resolver_for(solver)
    recharge_series_m_s = resolver.resolve_recharge_series(nper)
    active_recharge = resolver.has_active_recharge_payload(recharge_series_m_s)
    well_flux_by_period_m3_s = np.asarray(
        resolver.resolve_well_flux_by_period(nper),
        dtype=float,
    )
    ocean_series_m = resolver.resolve_ocean_series(nper)
    dirichlet_supports_by_period = resolver.resolved_dirichlet_supports_by_period(
        nper,
        ocean_series_m=ocean_series_m,
    )
    prescribed_heads_by_period = tuple(
        np.asarray(
            resolver.project_dirichlet_supports_to_cells(period_supports),
            dtype=float,
        )
        for period_supports in dirichlet_supports_by_period
    )
    boundary_heads_by_period = tuple(
        np.asarray(
            resolver.project_dirichlet_supports_to_edges(period_supports),
            dtype=float,
        )
        for period_supports in dirichlet_supports_by_period
    )
    ocean_supported_cell_masks = tuple(
        np.asarray(mask, dtype=bool)
        for mask in resolver.ocean_supported_cell_masks_by_period(
            ocean_series_m,
            nper=nper,
        )
    )
    drainage_conductance_series_m2_s = np.asarray(
        resolver.resolve_drainage_conductance_series(nper),
        dtype=float,
    )
    return ResolvedRuntimeForcing(
        recharge_series_m_s=recharge_series_m_s,
        active_recharge=bool(active_recharge),
        well_flux_by_period_m3_s=well_flux_by_period_m3_s,
        ocean_series_m=ocean_series_m,
        dirichlet_supports_by_period=tuple(
            tuple(period_supports) for period_supports in dirichlet_supports_by_period
        ),
        prescribed_heads_by_period=prescribed_heads_by_period,
        boundary_heads_by_period=boundary_heads_by_period,
        ocean_supported_cell_masks=ocean_supported_cell_masks,
        drainage_conductance_series_m2_s=drainage_conductance_series_m2_s,
    )


def resolve_boundary_forcing_by_period(
    solver: BoussinesqForcingSolver,
    *,
    nper: int,
) -> ResolvedRuntimeForcing:
    """Backward-compatible alias kept for pre-refactor callers."""
    return resolve_runtime_forcing_by_period(solver, nper=nper)


ResolvedBoundaryForcing = ResolvedRuntimeForcing


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
    "ResolvedRuntimeForcing",
    "apply_ocean_drainage_mask",
    "resolve_boundary_forcing_by_period",
    "resolve_runtime_forcing_by_period",
]
