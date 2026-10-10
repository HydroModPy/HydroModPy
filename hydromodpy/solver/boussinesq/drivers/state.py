"""Helpers to build Boussinesq runtime state from steady/transient solve traces."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from hydromodpy.solver.boussinesq.assembly import BoussinesqAssembly
from hydromodpy.solver.boussinesq.assembly.boundary_flux_reconstruction import (
    rebuild_boundary_edge_flux,
)
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def _balance_residual_m3_s(assembly: BoussinesqAssembly) -> np.ndarray:
    """Return the water-balance residual of each cell once its constant-head flux is counted.

    On a cell with an imposed head the flow residual is not an error: it is the
    water the boundary exchanges, and the constant-head flux carries it. The
    balance residual is zero there and equals the flow residual elsewhere, so
    its sum is the closure error of the run.
    """
    return np.asarray(assembly.residual_m3_s, dtype=float) + np.asarray(
        assembly.prescribed_head_flux_m3_s, dtype=float
    )


@dataclass(frozen=True)
class PeriodFluxes:
    """The fluxes a stress period exports, one array per quantity.

    One time step gives its own fluxes. A period cut into several takes their
    mean, weighted by step length: a stamp closes its period, so a flux
    stamped at the period end is its mean over the period. The rates are in
    m/s, the other fluxes in m3/s.
    """

    saturation_excess_rate_m_s: np.ndarray
    dry_deficit_rate_m_s: np.ndarray
    recharge_rate_m_s: np.ndarray
    well_flux_m3_s: np.ndarray
    internal_edge_flux_m3_s: np.ndarray
    boundary_edge_flux_m3_s: np.ndarray
    prescribed_head_flux_m3_s: np.ndarray
    drainage_flux_m3_s: np.ndarray
    residual_m3_s: np.ndarray

    @classmethod
    def from_step(
        cls,
        *,
        mesh: BoussinesqMesh,
        head_m: np.ndarray,
        assembly: BoussinesqAssembly,
        prescribed_head_m_by_cell: np.ndarray,
        boundary_head_m_by_edge: np.ndarray | None = None,
    ) -> PeriodFluxes:
        """Return the fluxes of one accepted time step."""
        dry_deficit = assembly.dry_deficit_rate_m_s
        return cls(
            saturation_excess_rate_m_s=np.asarray(
                assembly.saturation_excess_rate_m_s, dtype=float
            ).copy(),
            dry_deficit_rate_m_s=(
                np.zeros(mesh.n_cells, dtype=float)
                if dry_deficit is None
                else np.asarray(dry_deficit, dtype=float).copy()
            ),
            recharge_rate_m_s=np.asarray(assembly.recharge_rate_m_s, dtype=float).copy(),
            well_flux_m3_s=np.asarray(assembly.well_flux_m3_s, dtype=float).copy(),
            internal_edge_flux_m3_s=np.asarray(
                assembly.internal_edge_flux_m3_s, dtype=float
            ).copy(),
            boundary_edge_flux_m3_s=rebuild_boundary_edge_flux(
                mesh=mesh,
                head_m=head_m,
                assembly_boundary_edge_flux_m3_s=assembly.boundary_edge_flux_m3_s,
                internal_edge_flux_m3_s=assembly.internal_edge_flux_m3_s,
                boundary_head_m_by_edge=boundary_head_m_by_edge,
                prescribed_head_flux_m3_s=assembly.prescribed_head_flux_m3_s,
                prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            ),
            prescribed_head_flux_m3_s=np.asarray(
                assembly.prescribed_head_flux_m3_s, dtype=float
            ).copy(),
            drainage_flux_m3_s=np.asarray(assembly.drainage_flux_m3_s, dtype=float).copy(),
            residual_m3_s=_balance_residual_m3_s(assembly),
        )

    @classmethod
    def period_mean(cls, steps: list[PeriodFluxes], weights: list[float]) -> PeriodFluxes:
        """Return the step-length-weighted mean of the fluxes of one period.

        One step of weight 1.0 is returned unchanged, so a period of one
        step exports exactly the fluxes of its solve.
        """
        if len(steps) != len(weights) or not steps:
            raise ValueError(f"{len(steps)} steps for {len(weights)} weights.")
        if len(steps) == 1 and float(weights[0]) == 1.0:
            return steps[0]
        means: dict[str, np.ndarray] = {}
        for name in cls.__dataclass_fields__:
            total = float(weights[0]) * np.asarray(getattr(steps[0], name), dtype=float)
            for weight, step in zip(weights[1:], steps[1:], strict=True):
                total = total + float(weight) * np.asarray(getattr(step, name), dtype=float)
            means[name] = total
        return cls(**means)


@dataclass
class TransientRuntimeHistory:
    """Accumulate one transient run history before exporting the accepted state."""

    head_history: list[np.ndarray] = field(default_factory=list)
    thickness_history: list[np.ndarray] = field(default_factory=list)
    saturation_excess_history: list[np.ndarray] = field(default_factory=list)
    dry_deficit_history: list[np.ndarray] = field(default_factory=list)
    recharge_rate_history: list[np.ndarray] = field(default_factory=list)
    well_flux_history: list[np.ndarray] = field(default_factory=list)
    internal_edge_flux_history: list[np.ndarray] = field(default_factory=list)
    boundary_edge_flux_history: list[np.ndarray] = field(default_factory=list)
    prescribed_head_flux_history: list[np.ndarray] = field(default_factory=list)
    prescribed_head_history: list[np.ndarray] = field(default_factory=list)
    drainage_flux_history: list[np.ndarray] = field(default_factory=list)
    residual_history: list[np.ndarray] = field(default_factory=list)

    @classmethod
    def initialize(
        cls,
        *,
        mesh: BoussinesqMesh,
        head_m: np.ndarray,
        saturated_thickness_m: np.ndarray,
    ) -> TransientRuntimeHistory:
        """Create one history starting from the accepted initial state."""
        return cls(
            head_history=[np.asarray(head_m, dtype=float).copy()],
            thickness_history=[np.asarray(saturated_thickness_m, dtype=float).copy()],
            saturation_excess_history=[np.zeros(mesh.n_cells, dtype=float)],
            dry_deficit_history=[np.zeros(mesh.n_cells, dtype=float)],
            recharge_rate_history=[np.zeros(mesh.n_cells, dtype=float)],
            well_flux_history=[np.zeros(mesh.n_cells, dtype=float)],
            internal_edge_flux_history=[np.zeros(mesh.n_edges, dtype=float)],
            boundary_edge_flux_history=[np.zeros(mesh.n_edges, dtype=float)],
            prescribed_head_flux_history=[np.zeros(mesh.n_cells, dtype=float)],
            prescribed_head_history=[np.full(mesh.n_cells, np.nan, dtype=float)],
            drainage_flux_history=[np.zeros(mesh.n_cells, dtype=float)],
            residual_history=[np.zeros(mesh.n_cells, dtype=float)],
        )

    def start_from(self, *, head_m: np.ndarray, saturated_thickness_m: np.ndarray) -> None:
        """Replace the initial state by the state of a steady first period.

        A steady period holds one state over its whole length, its start
        included, so the storage change over that period is zero.
        """
        self.head_history[0] = np.asarray(head_m, dtype=float).copy()
        self.thickness_history[0] = np.asarray(saturated_thickness_m, dtype=float).copy()

    def append_step(
        self,
        *,
        mesh: BoussinesqMesh,
        head_m: np.ndarray,
        assembly: BoussinesqAssembly,
        prescribed_head_m_by_cell: np.ndarray,
        boundary_head_m_by_edge: np.ndarray | None = None,
    ) -> None:
        """Append one period solved in one accepted nonlinear step."""
        self.append_period(
            head_m=head_m,
            saturated_thickness_m=assembly.saturated_thickness_m,
            fluxes=PeriodFluxes.from_step(
                mesh=mesh,
                head_m=head_m,
                assembly=assembly,
                prescribed_head_m_by_cell=prescribed_head_m_by_cell,
                boundary_head_m_by_edge=boundary_head_m_by_edge,
            ),
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        )

    def append_period(
        self,
        *,
        head_m: np.ndarray,
        saturated_thickness_m: np.ndarray,
        fluxes: PeriodFluxes,
        prescribed_head_m_by_cell: np.ndarray,
    ) -> None:
        """Append one stress period: its end state and the fluxes it exports."""
        self.head_history.append(np.asarray(head_m, dtype=float).copy())
        self.thickness_history.append(np.asarray(saturated_thickness_m, dtype=float).copy())
        self.saturation_excess_history.append(fluxes.saturation_excess_rate_m_s)
        self.dry_deficit_history.append(fluxes.dry_deficit_rate_m_s)
        self.recharge_rate_history.append(fluxes.recharge_rate_m_s)
        self.well_flux_history.append(fluxes.well_flux_m3_s)
        self.internal_edge_flux_history.append(fluxes.internal_edge_flux_m3_s)
        self.boundary_edge_flux_history.append(fluxes.boundary_edge_flux_m3_s)
        self.prescribed_head_flux_history.append(fluxes.prescribed_head_flux_m3_s)
        self.prescribed_head_history.append(
            np.asarray(prescribed_head_m_by_cell, dtype=float).copy()
        )
        self.drainage_flux_history.append(fluxes.drainage_flux_m3_s)
        self.residual_history.append(fluxes.residual_m3_s)

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
        final_dry_deficit = np.asarray(
            self.dry_deficit_history[-1],
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
            dry_deficit_rate_m_s=final_dry_deficit.copy(),
            recharge_rate_history_m_s=np.vstack(self.recharge_rate_history),
            well_flux_history_m3_s=np.vstack(self.well_flux_history),
            head_history_m=np.vstack(self.head_history),
            saturated_thickness_history_m=np.vstack(self.thickness_history),
            saturation_excess_history_m_s=np.vstack(self.saturation_excess_history),
            dry_deficit_history_m_s=np.vstack(self.dry_deficit_history),
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
            residual_history_m3_s=np.vstack(self.residual_history),
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
        dry_deficit_rate_m_s=(
            np.zeros(mesh.n_cells, dtype=float)
            if assembly.dry_deficit_rate_m_s is None
            else np.asarray(assembly.dry_deficit_rate_m_s, dtype=float).copy()
        ),
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
        dry_deficit_history_m_s=np.asarray(
            [
                np.zeros(mesh.n_cells, dtype=float)
                if assembly.dry_deficit_rate_m_s is None
                else assembly.dry_deficit_rate_m_s
            ],
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
        residual_history_m3_s=np.asarray([_balance_residual_m3_s(assembly)], dtype=float),
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
    "PeriodFluxes",
    "TransientRuntimeHistory",
    "build_steady_runtime_state",
    "build_transient_activity_flags",
]
