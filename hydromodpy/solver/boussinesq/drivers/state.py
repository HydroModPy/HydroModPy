"""Helpers to build Boussinesq runtime state from steady/transient solve traces."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from hydromodpy.solver.boussinesq.assembly import BoussinesqAssembly
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.assembly.boundary_flux_reconstruction import (
    rebuild_boundary_edge_flux,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


@dataclass
class TransientRuntimeHistory:
    """Accumulate one transient run history before exporting the accepted state."""

    head_history: list[np.ndarray] = field(default_factory=list)
    thickness_history: list[np.ndarray] = field(default_factory=list)
    saturation_excess_history: list[np.ndarray] = field(default_factory=list)
    recharge_rate_history: list[np.ndarray] = field(default_factory=list)
    well_flux_history: list[np.ndarray] = field(default_factory=list)
    internal_edge_flux_history: list[np.ndarray] = field(default_factory=list)
    boundary_edge_flux_history: list[np.ndarray] = field(default_factory=list)
    prescribed_head_flux_history: list[np.ndarray] = field(default_factory=list)
    prescribed_head_history: list[np.ndarray] = field(default_factory=list)
    drainage_flux_history: list[np.ndarray] = field(default_factory=list)

    @classmethod
    def initialize(
        cls,
        *,
        mesh: BoussinesqMesh,
        head_m: np.ndarray,
        saturated_thickness_m: np.ndarray,
    ) -> "TransientRuntimeHistory":
        """Create one history starting from the accepted initial state."""
        return cls(
            head_history=[np.asarray(head_m, dtype=float).copy()],
            thickness_history=[np.asarray(saturated_thickness_m, dtype=float).copy()],
            saturation_excess_history=[np.zeros(mesh.n_cells, dtype=float)],
            recharge_rate_history=[np.zeros(mesh.n_cells, dtype=float)],
            well_flux_history=[np.zeros(mesh.n_cells, dtype=float)],
            internal_edge_flux_history=[np.zeros(mesh.n_edges, dtype=float)],
            boundary_edge_flux_history=[np.zeros(mesh.n_edges, dtype=float)],
            prescribed_head_flux_history=[np.zeros(mesh.n_cells, dtype=float)],
            prescribed_head_history=[np.full(mesh.n_cells, np.nan, dtype=float)],
            drainage_flux_history=[np.zeros(mesh.n_cells, dtype=float)],
        )

    def append_step(
        self,
        *,
        mesh: BoussinesqMesh,
        head_m: np.ndarray,
        assembly: BoussinesqAssembly,
        prescribed_head_m_by_cell: np.ndarray,
        boundary_head_m_by_edge: np.ndarray | None = None,
    ) -> None:
        """Append one accepted nonlinear step to the history."""
        boundary_edge_flux = rebuild_boundary_edge_flux(
            mesh=mesh,
            head_m=head_m,
            assembly_boundary_edge_flux_m3_s=assembly.boundary_edge_flux_m3_s,
            internal_edge_flux_m3_s=assembly.internal_edge_flux_m3_s,
            boundary_head_m_by_edge=boundary_head_m_by_edge,
            prescribed_head_flux_m3_s=assembly.prescribed_head_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        )
        self.head_history.append(np.asarray(head_m, dtype=float).copy())
        self.thickness_history.append(
            np.asarray(assembly.saturated_thickness_m, dtype=float).copy()
        )
        self.saturation_excess_history.append(
            np.asarray(assembly.saturation_excess_rate_m_s, dtype=float).copy()
        )
        self.recharge_rate_history.append(
            np.asarray(assembly.recharge_rate_m_s, dtype=float).copy()
        )
        self.well_flux_history.append(np.asarray(assembly.well_flux_m3_s, dtype=float).copy())
        self.internal_edge_flux_history.append(
            np.asarray(assembly.internal_edge_flux_m3_s, dtype=float).copy()
        )
        self.boundary_edge_flux_history.append(boundary_edge_flux)
        self.prescribed_head_flux_history.append(
            np.asarray(assembly.prescribed_head_flux_m3_s, dtype=float).copy()
        )
        self.prescribed_head_history.append(
            np.asarray(prescribed_head_m_by_cell, dtype=float).copy()
        )
        self.drainage_flux_history.append(
            np.asarray(assembly.drainage_flux_m3_s, dtype=float).copy()
        )

    def build_runtime_state(
        self,
        *,
        period_lengths_seconds: tuple[float, ...],
        nonlinear_iterations: tuple[int, ...],
        converged_by_period: tuple[bool, ...],
    ) -> BoussinesqState:
        """Build one normalized runtime state from the accumulated history."""
        final_head = np.asarray(self.head_history[-1], dtype=float)
        final_thickness = np.asarray(self.thickness_history[-1], dtype=float)
        final_recharge_rate = np.asarray(self.recharge_rate_history[-1], dtype=float)
        final_well_flux = np.asarray(self.well_flux_history[-1], dtype=float)
        final_saturation_excess = np.asarray(
            self.saturation_excess_history[-1],
            dtype=float,
        )
        final_internal_flux = np.asarray(
            self.internal_edge_flux_history[-1],
            dtype=float,
        )
        final_boundary_edge_flux = np.asarray(self.boundary_edge_flux_history[-1], dtype=float)
        final_prescribed_head_flux = np.asarray(
            self.prescribed_head_flux_history[-1],
            dtype=float,
        )
        final_prescribed_head = np.asarray(
            self.prescribed_head_history[-1],
            dtype=float,
        )
        final_drainage_flux = np.asarray(self.drainage_flux_history[-1], dtype=float)
        return BoussinesqState.from_runtime(
            head_m=final_head.copy(),
            saturated_thickness_m=final_thickness.copy(),
            recharge_rate_m_s=final_recharge_rate.copy(),
            well_flux_m3_s=final_well_flux.copy(),
            saturation_excess_rate_m_s=final_saturation_excess.copy(),
            recharge_rate_history_m_s=np.vstack(self.recharge_rate_history),
            well_flux_history_m3_s=np.vstack(self.well_flux_history),
            head_history_m=np.vstack(self.head_history),
            saturated_thickness_history_m=np.vstack(self.thickness_history),
            saturation_excess_history_m_s=np.vstack(self.saturation_excess_history),
            internal_edge_flux_m3_s=final_internal_flux.copy(),
            internal_edge_flux_history_m3_s=np.vstack(self.internal_edge_flux_history),
            boundary_edge_flux_m3_s=final_boundary_edge_flux.copy(),
            boundary_edge_flux_history_m3_s=np.vstack(self.boundary_edge_flux_history),
            prescribed_head_flux_m3_s=final_prescribed_head_flux.copy(),
            prescribed_head_flux_history_m3_s=np.vstack(self.prescribed_head_flux_history),
            prescribed_head_m_by_cell=final_prescribed_head.copy(),
            prescribed_head_history_m_by_cell=np.vstack(self.prescribed_head_history),
            drainage_flux_m3_s=final_drainage_flux.copy(),
            drainage_flux_history_m3_s=np.vstack(self.drainage_flux_history),
            period_lengths_seconds=period_lengths_seconds,
            nonlinear_iterations=nonlinear_iterations,
            converged_by_period=converged_by_period,
        )


def build_steady_runtime_state(
    *,
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    assembly: BoussinesqAssembly,
    prescribed_head_m_by_cell: np.ndarray,
    boundary_head_m_by_edge: np.ndarray | None = None,
    nonlinear_iterations: int,
    converged: bool,
) -> BoussinesqState:
    """Build one normalized state from one accepted steady solve."""
    boundary_edge_flux = rebuild_boundary_edge_flux(
        mesh=mesh,
        head_m=head_m,
        assembly_boundary_edge_flux_m3_s=assembly.boundary_edge_flux_m3_s,
        internal_edge_flux_m3_s=assembly.internal_edge_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_flux_m3_s=assembly.prescribed_head_flux_m3_s,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    return BoussinesqState.from_runtime(
        head_m=np.asarray(head_m, dtype=float).copy(),
        saturated_thickness_m=np.asarray(
            assembly.saturated_thickness_m,
            dtype=float,
        ).copy(),
        recharge_rate_m_s=np.asarray(assembly.recharge_rate_m_s, dtype=float).copy(),
        well_flux_m3_s=np.asarray(assembly.well_flux_m3_s, dtype=float).copy(),
        saturation_excess_rate_m_s=np.asarray(
            assembly.saturation_excess_rate_m_s,
            dtype=float,
        ).copy(),
        recharge_rate_history_m_s=np.asarray([assembly.recharge_rate_m_s], dtype=float),
        well_flux_history_m3_s=np.asarray([assembly.well_flux_m3_s], dtype=float),
        head_history_m=np.asarray([head_m], dtype=float),
        saturated_thickness_history_m=np.asarray(
            [assembly.saturated_thickness_m],
            dtype=float,
        ),
        saturation_excess_history_m_s=np.asarray(
            [assembly.saturation_excess_rate_m_s],
            dtype=float,
        ),
        internal_edge_flux_m3_s=np.asarray(
            assembly.internal_edge_flux_m3_s,
            dtype=float,
        ).copy(),
        internal_edge_flux_history_m3_s=np.asarray(
            [assembly.internal_edge_flux_m3_s],
            dtype=float,
        ),
        boundary_edge_flux_m3_s=boundary_edge_flux.copy(),
        boundary_edge_flux_history_m3_s=np.asarray(
            [boundary_edge_flux],
            dtype=float,
        ),
        prescribed_head_flux_m3_s=np.asarray(
            assembly.prescribed_head_flux_m3_s,
            dtype=float,
        ).copy(),
        prescribed_head_flux_history_m3_s=np.asarray(
            [assembly.prescribed_head_flux_m3_s],
            dtype=float,
        ),
        prescribed_head_m_by_cell=np.asarray(
            prescribed_head_m_by_cell,
            dtype=float,
        ).copy(),
        prescribed_head_history_m_by_cell=np.asarray(
            [prescribed_head_m_by_cell],
            dtype=float,
        ),
        drainage_flux_m3_s=np.asarray(assembly.drainage_flux_m3_s, dtype=float).copy(),
        drainage_flux_history_m3_s=np.asarray(
            [assembly.drainage_flux_m3_s],
            dtype=float,
        ),
        period_lengths_seconds=(),
        nonlinear_iterations=(int(nonlinear_iterations),),
        converged_by_period=(bool(converged),),
    )


def build_transient_activity_flags(
    *,
    recharge_series_m_s: tuple[float | np.ndarray, ...],
    well_flux_by_period_m3_s: np.ndarray,
    dirichlet_supports_by_period: tuple[tuple[object, ...], ...],
    prescribed_heads_by_period: tuple[np.ndarray, ...] | None = None,
    ocean_supported_cell_masks: tuple[np.ndarray, ...],
    drainage_conductance_series_m2_s: np.ndarray,
) -> dict[str, bool]:
    """Return one compact activity-flag mapping for runtime summaries."""
    active_dirichlet_supports = bool(
        any(len(period_supports) > 0 for period_supports in dirichlet_supports_by_period)
    )
    active_prescribed = bool(
        prescribed_heads_by_period is not None
        and any(np.isfinite(values).any() for values in prescribed_heads_by_period)
    )
    return {
        "active_recharge": any(
            bool(np.any(np.asarray(payload, dtype=float) != 0.0)) for payload in recharge_series_m_s
        ),
        "active_wells": bool(np.any(well_flux_by_period_m3_s != 0.0)),
        "active_prescribed_head_bc": active_prescribed,
        "active_dirichlet_bc": bool(active_dirichlet_supports or active_prescribed),
        "active_ocean": bool(any(np.any(mask) for mask in ocean_supported_cell_masks)),
        "active_drainage": bool(np.any(drainage_conductance_series_m2_s != 0.0)),
    }


__all__ = [
    "TransientRuntimeHistory",
    "build_steady_runtime_state",
    "build_transient_activity_flags",
]
