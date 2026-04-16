"""Finite-volume assembly helpers shared by all current Boussinesq runtimes.

This is the physical heart of the package. Given a candidate head vector, the
functions in this module reconstruct:

- the saturated thickness in each cell,
- the transmissivity implied by that thickness,
- the internal and boundary fluxes,
- the drainage and saturation-excess source terms,
- the final residual that the nonlinear solver must drive to zero.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

_MIN_DISTANCE_M = 1.0e-12


@dataclass(frozen=True)
class BoussinesqAssembly:
    """Fully assembled nonlinear state for one candidate head field.

    Returning all intermediate arrays is deliberate: it makes debugging,
    diagnostics and post-processing much easier than returning only the final
    residual.
    """

    head_m: np.ndarray
    saturated_thickness_m: np.ndarray
    transmissivity_m2_s: np.ndarray
    recharge_rate_m_s: np.ndarray
    well_flux_m3_s: np.ndarray
    saturation_excess_rate_m_s: np.ndarray
    internal_edge_flux_m3_s: np.ndarray
    prescribed_head_flux_m3_s: np.ndarray
    prescribed_head_m_by_cell: np.ndarray
    boundary_edge_flux_m3_s: np.ndarray
    drainage_flux_m3_s: np.ndarray
    residual_m3_s: np.ndarray


@dataclass(frozen=True)
class _BoussinesqSpatialTerms:
    """Spatial contributions shared by steady and transient assembly.

    The transient and steady residuals differ only by the storage term. All
    other operators are assembled once here and reused by both residual builders.
    """

    head_m: np.ndarray
    saturated_thickness_m: np.ndarray
    transmissivity_m2_s: np.ndarray
    recharge_rate_m_s: np.ndarray
    well_flux_m3_s: np.ndarray
    saturation_excess_rate_m_s: np.ndarray
    internal_edge_flux_m3_s: np.ndarray
    internal_flux_residual_m3_s: np.ndarray
    boundary_edge_flux_m3_s: np.ndarray
    boundary_head_flux_residual_m3_s: np.ndarray
    drainage_flux_m3_s: np.ndarray


@dataclass(frozen=True)
class _BoundaryHeadInputs:
    """Normalized boundary-head inputs used internally by assembly/Jacobian code."""

    head_m: np.ndarray
    boundary_head_m_by_edge: np.ndarray
    prescribed_head_m_by_cell: np.ndarray
    prescribed_mask: np.ndarray


def _as_cell_vector(
    values: np.ndarray | float | None,
    *,
    n_cells: int,
    label: str,
) -> np.ndarray:
    """Return one cell-aligned vector from a scalar, array or missing payload."""
    if values is None:
        return np.zeros(n_cells, dtype=float)
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0:
        return np.zeros(n_cells, dtype=float)
    if array.size == 1:
        return np.full(n_cells, float(array[0]), dtype=float)
    if array.size != int(n_cells):
        raise ValueError(
            f"{label} must be scalar or have length {int(n_cells)}; got {int(array.size)}."
        )
    return array.astype(float, copy=False)


def _as_prescribed_head_cell_vector(
    values: np.ndarray | None,
    *,
    n_cells: int,
    label: str,
) -> np.ndarray:
    """Return one cell-aligned prescribed-head vector with NaN on free cells."""
    if values is None:
        return np.full(n_cells, np.nan, dtype=float)
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size != int(n_cells):
        raise ValueError(
            f"{label} must have length {int(n_cells)}; got {int(array.size)}."
        )
    return array.astype(float, copy=False)


def _as_edge_vector(
    values: np.ndarray | None,
    *,
    n_edges: int,
    label: str,
) -> np.ndarray:
    """Return one edge-aligned vector from an optional array payload."""
    if values is None:
        return np.full(n_edges, np.nan, dtype=float)
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size != int(n_edges):
        raise ValueError(
            f"{label} must have length {int(n_edges)}; got {int(array.size)}."
        )
    return array.astype(float, copy=False)


def apply_prescribed_head_to_cells(
    head_m: np.ndarray,
    *,
    prescribed_head_m_by_cell: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Overwrite prescribed cells with their Dirichlet value."""
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    prescribed = _as_prescribed_head_cell_vector(
        prescribed_head_m_by_cell,
        n_cells=head.size,
        label="prescribed_head_m_by_cell",
    )
    mask = np.isfinite(prescribed)
    if np.any(mask):
        head[mask] = prescribed[mask]
    return head, prescribed


def _resolve_boundary_head_inputs(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None,
) -> _BoundaryHeadInputs:
    """Normalize the two supported Dirichlet representations to one internal view.

    The canonical path is now cell-prescribed Dirichlet
    (`prescribed_head_m_by_cell`). The optional edge-supported boundary-head
    view is kept only for focused low-level diagnostics and tests.
    """
    head = np.asarray(head_m, dtype=float).reshape(-1)
    if head.size != int(mesh.n_cells):
        raise ValueError(
            f"head_m length must match mesh.n_cells ({head.size} != {int(mesh.n_cells)})."
        )
    boundary_head = _as_edge_vector(
        boundary_head_m_by_edge,
        n_edges=mesh.n_edges,
        label="boundary_head_m_by_edge",
    )
    prescribed_head = _as_prescribed_head_cell_vector(
        prescribed_head_m_by_cell,
        n_cells=mesh.n_cells,
        label="prescribed_head_m_by_cell",
    )
    if np.any(np.isfinite(boundary_head)) and np.any(np.isfinite(prescribed_head)):
        raise ValueError(
            "boundary_head_m_by_edge and prescribed_head_m_by_cell are mutually exclusive."
        )
    if np.any(np.isfinite(prescribed_head)):
        head, prescribed_head = apply_prescribed_head_to_cells(
            head,
            prescribed_head_m_by_cell=prescribed_head,
        )
    prescribed_mask = np.isfinite(prescribed_head)
    return _BoundaryHeadInputs(
        head_m=head,
        boundary_head_m_by_edge=boundary_head,
        prescribed_head_m_by_cell=prescribed_head,
        prescribed_mask=prescribed_mask,
    )


def _finalize_boundary_constrained_residual(
    *,
    head_m: np.ndarray,
    raw_residual_m3_s: np.ndarray,
    prescribed_head_m_by_cell: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return residual plus diagnostic prescribed-head flux after constraint enforcement."""
    prescribed_mask = np.isfinite(np.asarray(prescribed_head_m_by_cell, dtype=float))
    prescribed_head_flux = np.zeros_like(np.asarray(raw_residual_m3_s, dtype=float))
    residual = np.asarray(raw_residual_m3_s, dtype=float).copy()
    if np.any(prescribed_mask):
        prescribed_head_flux[prescribed_mask] = -residual[prescribed_mask]
        residual[prescribed_mask] = (
            np.asarray(head_m, dtype=float)[prescribed_mask]
            - np.asarray(prescribed_head_m_by_cell, dtype=float)[prescribed_mask]
        )
    return residual, prescribed_head_flux


def _edge_to_stage_tau_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return transmissive factors used for imposed-head edge exchanges."""
    head = np.asarray(head_m, dtype=float)
    saturated_thickness = saturated_thickness_from_head(mesh, head)
    tau_a = np.zeros(mesh.n_edges, dtype=float)
    tau_b = np.zeros(mesh.n_edges, dtype=float)
    for edge_index in range(mesh.n_edges):
        cell_a = int(mesh.edge_cell_a[edge_index])
        conductivity = max(float(mesh.hydraulic_conductivity_m_s[cell_a]), 0.0)
        thickness = max(float(saturated_thickness[cell_a]), 0.0)
        distance_a_m = max(
            float(mesh.edge_midpoint_distance_to_cell_a_m[edge_index]),
            _MIN_DISTANCE_M,
        )
        tau_a[edge_index] = (
            conductivity
            * thickness
            * float(mesh.edge_length_m[edge_index])
            / distance_a_m
        )
        cell_b = int(mesh.edge_cell_b[edge_index])
        if cell_b >= 0:
            conductivity_b = max(float(mesh.hydraulic_conductivity_m_s[cell_b]), 0.0)
            thickness_b = max(float(saturated_thickness[cell_b]), 0.0)
            distance_b_m = max(
                float(mesh.edge_midpoint_distance_to_cell_b_m[edge_index]),
                _MIN_DISTANCE_M,
            )
            tau_b[edge_index] = (
                conductivity_b
                * thickness_b
                * float(mesh.edge_length_m[edge_index])
                / distance_b_m
            )
    return tau_a, tau_b


def boundary_head_edge_flux_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    boundary_head_m_by_edge: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return fluxes created by edge-supported Dirichlet heads."""
    boundary_heads = _as_edge_vector(
        boundary_head_m_by_edge,
        n_edges=mesh.n_edges,
        label="boundary_head_m_by_edge",
    )
    tau_a, tau_b = _edge_to_stage_tau_from_head(mesh, head_m)
    head = np.asarray(head_m, dtype=float)
    edge_flux = np.zeros(mesh.n_edges, dtype=float)
    residual = np.zeros(mesh.n_cells, dtype=float)
    for edge_index in range(mesh.n_edges):
        boundary_head = float(boundary_heads[edge_index])
        if not np.isfinite(boundary_head):
            continue
        cell_a = int(mesh.edge_cell_a[edge_index])
        flux_a = -float(tau_a[edge_index]) * (
            boundary_head - float(head[cell_a])
        )
        residual[cell_a] += flux_a
        edge_flux[edge_index] += flux_a
        cell_b = int(mesh.edge_cell_b[edge_index])
        if cell_b >= 0 and float(tau_b[edge_index]) > 0.0:
            flux_b = -float(tau_b[edge_index]) * (
                boundary_head - float(head[cell_b])
            )
            residual[cell_b] += flux_b
            edge_flux[edge_index] += flux_b
    return edge_flux, residual


def saturated_thickness_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> np.ndarray:
    """Return the saturated thickness ``b(h)`` in each cell.

    The thickness is clipped between zero and the full aquifer thickness. This
    ensures that later operators always work with physically admissible values
    even if a nonlinear iterate temporarily overshoots.
    """
    max_thickness = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    return np.clip(np.asarray(head_m, dtype=float) - mesh.z_bottom_m, 0.0, max_thickness)


def transmissivity_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> np.ndarray:
    """Return the cell transmissivity ``T(h) = K b(h)``."""
    saturated_thickness_m = saturated_thickness_from_head(mesh, head_m)
    return mesh.hydraulic_conductivity_m_s * saturated_thickness_m


def _harmonic_conductivity(
    conductivity_a_m_s: float,
    conductivity_b_m_s: float,
) -> float:
    """Return the harmonic mean conductivity used on one interior edge."""
    if conductivity_a_m_s <= 0.0 or conductivity_b_m_s <= 0.0:
        return 0.0
    return 2.0 / ((1.0 / conductivity_a_m_s) + (1.0 / conductivity_b_m_s))


def internal_edge_flux_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> np.ndarray:
    """Return one oriented inter-cell flux per edge.

    The sign convention is important:

    - a positive value means water leaves ``cell_a``;
    - the same magnitude enters ``cell_b``.
    """
    head = np.asarray(head_m, dtype=float)
    saturated_thickness = saturated_thickness_from_head(mesh, head)
    internal_flux = np.zeros(mesh.n_edges, dtype=float)
    for edge_index in range(mesh.n_edges):
        cell_a = int(mesh.edge_cell_a[edge_index])
        cell_b = int(mesh.edge_cell_b[edge_index])
        if cell_b < 0:
            continue
        conductivity_a = float(mesh.hydraulic_conductivity_m_s[cell_a])
        conductivity_b = float(mesh.hydraulic_conductivity_m_s[cell_b])
        # The edge transmissivity uses a harmonic conductivity and an averaged
        # saturated thickness, which is the simplest conservative closure for
        # the current triangular cell-centered scheme.
        conductivity_edge = _harmonic_conductivity(conductivity_a, conductivity_b)
        thickness_edge = 0.5 * (
            float(saturated_thickness[cell_a]) + float(saturated_thickness[cell_b])
        )
        transmissivity_edge = conductivity_edge * thickness_edge
        distance_m = max(float(mesh.edge_distance_m[edge_index]), _MIN_DISTANCE_M)
        tau = transmissivity_edge * float(mesh.edge_length_m[edge_index]) / distance_m
        internal_flux[edge_index] = -tau * (float(head[cell_b]) - float(head[cell_a]))
    return internal_flux


def accumulate_internal_flux_residual(
    mesh: BoussinesqMesh,
    internal_edge_flux_m3_s: np.ndarray,
) -> np.ndarray:
    """Accumulate conservative internal fluxes into one cell residual vector."""
    residual = np.zeros(mesh.n_cells, dtype=float)
    edge_flux = np.asarray(internal_edge_flux_m3_s, dtype=float)
    for edge_index in range(mesh.n_edges):
        cell_a = int(mesh.edge_cell_a[edge_index])
        cell_b = int(mesh.edge_cell_b[edge_index])
        flux = float(edge_flux[edge_index])
        residual[cell_a] += flux
        if cell_b >= 0:
            residual[cell_b] -= flux
    return residual


def accumulate_boundary_flux_residual(
    mesh: BoussinesqMesh,
    boundary_edge_flux_m3_s: np.ndarray,
) -> np.ndarray:
    """Accumulate boundary fluxes into the residual of their owner cell."""
    residual = np.zeros(mesh.n_cells, dtype=float)
    edge_flux = np.asarray(boundary_edge_flux_m3_s, dtype=float)
    for edge_index in range(mesh.n_edges):
        if int(mesh.edge_cell_b[edge_index]) >= 0:
            continue
        cell_a = int(mesh.edge_cell_a[edge_index])
        residual[cell_a] += float(edge_flux[edge_index])
    return residual


def drainage_outflow_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> np.ndarray:
    """Return one drainage outflow per cell.

    Drainage is modeled as a top leakage activated only when the head rises
    above the cell top elevation. Positive values therefore always mean water
    leaves the aquifer toward the surface.
    """
    if drainage_conductance_m2_s is None:
        return np.zeros(mesh.n_cells, dtype=float)
    conductance = _as_cell_vector(
        drainage_conductance_m2_s,
        n_cells=mesh.n_cells,
        label="drainage_conductance_m2_s",
    )
    auto_conductance = mesh.hydraulic_conductivity_m_s * mesh.cell_area_m2
    effective_conductance = np.where(conductance > 0.0, conductance, auto_conductance)
    head = np.asarray(head_m, dtype=float)
    return effective_conductance * np.maximum(head - mesh.z_top_m, 0.0)


def regularized_partition_surface_rate_from_balance(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    lateral_flux_residual_m3_s: np.ndarray,
    surface_input_rate_m_s: np.ndarray | float | None,
    regularization_radius: float,
) -> np.ndarray:
    """Return the Marcais-style regularized partition surface flux.

    The closure follows the same structure as the regularized partition law:

    ``q_ex = G_r(theta) R(balance)``

    with:

    - ``theta`` the local saturation ratio,
    - ``balance`` the positive incoming balance that would keep filling the
      near-surface groundwater store,
    - ``G_r(theta) = exp(-(1-theta)/r)``,
    - ``R(u) = max(u, 0)``.

    The implementation remains written in terms of head because the current
    HydroModPy Boussinesq solver uses ``h`` as its primary unknown.
    """
    if float(regularization_radius) <= 0.0:
        raise ValueError("regularization_radius must be strictly positive.")

    max_thickness = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    thickness = saturated_thickness_from_head(mesh, head_m)
    saturation_ratio = np.divide(
        thickness,
        max_thickness,
        out=np.zeros(mesh.n_cells, dtype=float),
        where=max_thickness > 0.0,
    )
    surface_input = _as_cell_vector(
        surface_input_rate_m_s,
        n_cells=mesh.n_cells,
        label="surface_input_rate_m_s",
    )
    # A positive balance rate means the lateral system plus the surface input
    # would continue to raise the water table, so saturation excess may need to
    # release part of that water back to the surface.
    balance_rate = (
        -np.asarray(lateral_flux_residual_m3_s, dtype=float) / mesh.cell_area_m2
    ) + np.maximum(surface_input, 0.0)
    ramp_rate = np.maximum(balance_rate, 0.0)
    regularization = np.exp(
        -(1.0 - np.clip(saturation_ratio, 0.0, 1.0)) / float(regularization_radius)
    )
    return regularization * ramp_rate


def saturation_excess_rate_from_balance(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    lateral_flux_residual_m3_s: np.ndarray,
    surface_input_rate_m_s: np.ndarray | float | None,
    regularization_radius: float,
) -> np.ndarray:
    """Backward-compatible alias for the regularized partition surface law."""
    return regularized_partition_surface_rate_from_balance(
        mesh,
        head_m,
        lateral_flux_residual_m3_s=lateral_flux_residual_m3_s,
        surface_input_rate_m_s=surface_input_rate_m_s,
        regularization_radius=regularization_radius,
    )


def _resolve_saturation_excess_rate(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    lateral_flux_residual_m3_s: np.ndarray,
    recharge_rate_m_s: np.ndarray,
    regularization_radius: float,
    saturation_excess_rate_m_s: np.ndarray | float | None,
) -> np.ndarray:
    """Return the saturation-excess rate used by one residual assembly.

    The historical Boussinesq backend reconstructs ``q_ex`` from the smooth
    regularization law. The PETSc DAE backend instead provides ``q_ex`` as an
    explicit algebraic unknown. This helper centralizes that choice so the
    physical balance stays identical apart from how ``q_ex`` is obtained.
    """
    if saturation_excess_rate_m_s is not None:
        return _as_cell_vector(
            saturation_excess_rate_m_s,
            n_cells=mesh.n_cells,
            label="saturation_excess_rate_m_s",
        )
    return regularized_partition_surface_rate_from_balance(
        mesh,
        head_m,
        lateral_flux_residual_m3_s=lateral_flux_residual_m3_s,
        surface_input_rate_m_s=np.maximum(recharge_rate_m_s, 0.0),
        regularization_radius=float(regularization_radius),
    )


def _assemble_transient_residual_generic(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble the transient residual for one candidate head field.

    The transient residual is the steady residual plus the backward-Euler
    storage term. A converged transient step is obtained when every cell
    residual is close to zero.
    """
    if float(dt_seconds) <= 0.0:
        raise ValueError("dt_seconds must be strictly positive.")

    spatial_terms = _assemble_spatial_terms(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=float(regularization_radius),
    )
    head_prev = np.asarray(head_prev_m, dtype=float)
    temporal_term = (
        mesh.cell_area_m2
        * mesh.storage_coefficient
        * (spatial_terms.head_m - head_prev)
        / float(dt_seconds)
    )
    # Sign convention:
    # - positive flux residual terms remove water from the cell,
    # - recharge and positive well injection add water and are therefore
    #   subtracted from the residual.
    raw_residual = (
        temporal_term
        + spatial_terms.internal_flux_residual_m3_s
        + spatial_terms.boundary_head_flux_residual_m3_s
        + spatial_terms.drainage_flux_m3_s
        + mesh.cell_area_m2 * spatial_terms.saturation_excess_rate_m_s
        - mesh.cell_area_m2 * spatial_terms.recharge_rate_m_s
        - spatial_terms.well_flux_m3_s
    )
    boundary_inputs = _resolve_boundary_head_inputs(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    residual, prescribed_head_flux = _finalize_boundary_constrained_residual(
        head_m=np.asarray(head_m, dtype=float),
        raw_residual_m3_s=raw_residual,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
    )
    return BoussinesqAssembly(
        head_m=spatial_terms.head_m,
        saturated_thickness_m=spatial_terms.saturated_thickness_m,
        transmissivity_m2_s=spatial_terms.transmissivity_m2_s,
        recharge_rate_m_s=spatial_terms.recharge_rate_m_s,
        well_flux_m3_s=spatial_terms.well_flux_m3_s,
        saturation_excess_rate_m_s=spatial_terms.saturation_excess_rate_m_s,
        internal_edge_flux_m3_s=spatial_terms.internal_edge_flux_m3_s,
        prescribed_head_flux_m3_s=prescribed_head_flux,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
        boundary_edge_flux_m3_s=spatial_terms.boundary_edge_flux_m3_s,
        drainage_flux_m3_s=spatial_terms.drainage_flux_m3_s,
        residual_m3_s=residual,
    )


def assemble_transient_residual(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one transient residual on the canonical prescribed-cell path."""
    return _assemble_transient_residual_generic(
        mesh,
        head_m=head_m,
        head_prev_m=head_prev_m,
        dt_seconds=dt_seconds,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=regularization_radius,
    )


def _assemble_transient_residual_with_saturation_excess_generic(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    saturation_excess_rate_m_s: np.ndarray | float,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one transient residual with an externally supplied ``q_ex``.

    This variant is used by the PETSc complementarity runtime where
    ``saturation_excess_rate_m_s`` is no longer reconstructed from the smooth
    regularization law but solved as an algebraic unknown of the DAE system.
    """
    if float(dt_seconds) <= 0.0:
        raise ValueError("dt_seconds must be strictly positive.")

    spatial_terms = _assemble_spatial_terms(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=float(regularization_radius),
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
    )
    head_prev = np.asarray(head_prev_m, dtype=float)
    temporal_term = (
        mesh.cell_area_m2
        * mesh.storage_coefficient
        * (spatial_terms.head_m - head_prev)
        / float(dt_seconds)
    )
    raw_residual = (
        temporal_term
        + spatial_terms.internal_flux_residual_m3_s
        + spatial_terms.boundary_head_flux_residual_m3_s
        + spatial_terms.drainage_flux_m3_s
        + mesh.cell_area_m2 * spatial_terms.saturation_excess_rate_m_s
        - mesh.cell_area_m2 * spatial_terms.recharge_rate_m_s
        - spatial_terms.well_flux_m3_s
    )
    boundary_inputs = _resolve_boundary_head_inputs(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    residual, prescribed_head_flux = _finalize_boundary_constrained_residual(
        head_m=np.asarray(head_m, dtype=float),
        raw_residual_m3_s=raw_residual,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
    )
    return BoussinesqAssembly(
        head_m=spatial_terms.head_m,
        saturated_thickness_m=spatial_terms.saturated_thickness_m,
        transmissivity_m2_s=spatial_terms.transmissivity_m2_s,
        recharge_rate_m_s=spatial_terms.recharge_rate_m_s,
        well_flux_m3_s=spatial_terms.well_flux_m3_s,
        saturation_excess_rate_m_s=spatial_terms.saturation_excess_rate_m_s,
        internal_edge_flux_m3_s=spatial_terms.internal_edge_flux_m3_s,
        prescribed_head_flux_m3_s=prescribed_head_flux,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
        boundary_edge_flux_m3_s=spatial_terms.boundary_edge_flux_m3_s,
        drainage_flux_m3_s=spatial_terms.drainage_flux_m3_s,
        residual_m3_s=residual,
    )


def assemble_transient_residual_with_saturation_excess(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    saturation_excess_rate_m_s: np.ndarray | float,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one transient mixed residual on the canonical prescribed-cell path."""
    return _assemble_transient_residual_with_saturation_excess_generic(
        mesh,
        head_m=head_m,
        head_prev_m=head_prev_m,
        dt_seconds=dt_seconds,
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=regularization_radius,
    )


def _assemble_steady_residual_generic(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble the steady residual for one candidate head field."""
    spatial_terms = _assemble_spatial_terms(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=float(regularization_radius),
    )
    raw_residual = (
        spatial_terms.internal_flux_residual_m3_s
        + spatial_terms.boundary_head_flux_residual_m3_s
        + spatial_terms.drainage_flux_m3_s
        + mesh.cell_area_m2 * spatial_terms.saturation_excess_rate_m_s
        - mesh.cell_area_m2 * spatial_terms.recharge_rate_m_s
        - spatial_terms.well_flux_m3_s
    )
    boundary_inputs = _resolve_boundary_head_inputs(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    residual, prescribed_head_flux = _finalize_boundary_constrained_residual(
        head_m=np.asarray(head_m, dtype=float),
        raw_residual_m3_s=raw_residual,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
    )
    return BoussinesqAssembly(
        head_m=spatial_terms.head_m,
        saturated_thickness_m=spatial_terms.saturated_thickness_m,
        transmissivity_m2_s=spatial_terms.transmissivity_m2_s,
        recharge_rate_m_s=spatial_terms.recharge_rate_m_s,
        well_flux_m3_s=spatial_terms.well_flux_m3_s,
        saturation_excess_rate_m_s=spatial_terms.saturation_excess_rate_m_s,
        internal_edge_flux_m3_s=spatial_terms.internal_edge_flux_m3_s,
        prescribed_head_flux_m3_s=prescribed_head_flux,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
        boundary_edge_flux_m3_s=spatial_terms.boundary_edge_flux_m3_s,
        drainage_flux_m3_s=spatial_terms.drainage_flux_m3_s,
        residual_m3_s=residual,
    )


def assemble_steady_residual(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble the steady residual on the canonical prescribed-cell path."""
    return _assemble_steady_residual_generic(
        mesh,
        head_m=head_m,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=regularization_radius,
    )


def _assemble_steady_residual_with_saturation_excess_generic(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    saturation_excess_rate_m_s: np.ndarray | float,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one steady residual with an externally supplied ``q_ex``."""
    spatial_terms = _assemble_spatial_terms(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=float(regularization_radius),
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
    )
    raw_residual = (
        spatial_terms.internal_flux_residual_m3_s
        + spatial_terms.boundary_head_flux_residual_m3_s
        + spatial_terms.drainage_flux_m3_s
        + mesh.cell_area_m2 * spatial_terms.saturation_excess_rate_m_s
        - mesh.cell_area_m2 * spatial_terms.recharge_rate_m_s
        - spatial_terms.well_flux_m3_s
    )
    boundary_inputs = _resolve_boundary_head_inputs(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    residual, prescribed_head_flux = _finalize_boundary_constrained_residual(
        head_m=np.asarray(head_m, dtype=float),
        raw_residual_m3_s=raw_residual,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
    )
    return BoussinesqAssembly(
        head_m=spatial_terms.head_m,
        saturated_thickness_m=spatial_terms.saturated_thickness_m,
        transmissivity_m2_s=spatial_terms.transmissivity_m2_s,
        recharge_rate_m_s=spatial_terms.recharge_rate_m_s,
        well_flux_m3_s=spatial_terms.well_flux_m3_s,
        saturation_excess_rate_m_s=spatial_terms.saturation_excess_rate_m_s,
        internal_edge_flux_m3_s=spatial_terms.internal_edge_flux_m3_s,
        prescribed_head_flux_m3_s=prescribed_head_flux,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
        boundary_edge_flux_m3_s=spatial_terms.boundary_edge_flux_m3_s,
        drainage_flux_m3_s=spatial_terms.drainage_flux_m3_s,
        residual_m3_s=residual,
    )


def assemble_steady_residual_with_saturation_excess(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    saturation_excess_rate_m_s: np.ndarray | float,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one steady mixed residual on the canonical prescribed-cell path."""
    return _assemble_steady_residual_with_saturation_excess_generic(
        mesh,
        head_m=head_m,
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=regularization_radius,
    )


def _assemble_spatial_terms(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    boundary_head_m_by_edge: np.ndarray | None,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    regularization_radius: float,
    saturation_excess_rate_m_s: np.ndarray | float | None = None,
) -> _BoussinesqSpatialTerms:
    """Return the spatial/operator contributions for a candidate head field.

    This helper keeps the steady and transient assemblies in sync by computing
    all non-storage terms in one place.
    """
    boundary_inputs = _resolve_boundary_head_inputs(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    if np.any(np.isfinite(boundary_inputs.boundary_head_m_by_edge)):
        head = boundary_inputs.head_m
        boundary_edge_flux, boundary_head_flux_residual = (
            boundary_head_edge_flux_from_head(
                mesh,
                head,
                boundary_head_m_by_edge=boundary_inputs.boundary_head_m_by_edge,
            )
        )
    else:
        head = boundary_inputs.head_m
        boundary_edge_flux = np.zeros(mesh.n_edges, dtype=float)
        boundary_head_flux_residual = np.zeros(mesh.n_cells, dtype=float)
    saturated_thickness = saturated_thickness_from_head(mesh, head)
    transmissivity = mesh.hydraulic_conductivity_m_s * saturated_thickness
    internal_edge_flux = internal_edge_flux_from_head(mesh, head)
    internal_flux_residual = accumulate_internal_flux_residual(mesh, internal_edge_flux)
    recharge_rate = _as_cell_vector(
        recharge_rate_m_s,
        n_cells=mesh.n_cells,
        label="recharge_rate_m_s",
    )
    well_flux = _as_cell_vector(
        well_flux_m3_s,
        n_cells=mesh.n_cells,
        label="well_flux_m3_s",
    )
    # Saturation excess is evaluated after the lateral exchanges between cells.
    # Prescribed-head cells are enforced outside this physical assembly. When a
    # low-level edge-supported boundary view is provided, its flux contribution
    # is accumulated here before the surface partitioning step.
    saturation_excess_rate = _resolve_saturation_excess_rate(
        mesh,
        head_m=head,
        lateral_flux_residual_m3_s=(
            internal_flux_residual + boundary_head_flux_residual
        ),
        recharge_rate_m_s=recharge_rate,
        regularization_radius=float(regularization_radius),
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
    )
    drainage_flux = drainage_outflow_from_head(
        mesh,
        head,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    return _BoussinesqSpatialTerms(
        head_m=head,
        saturated_thickness_m=saturated_thickness,
        transmissivity_m2_s=transmissivity,
        recharge_rate_m_s=recharge_rate,
        well_flux_m3_s=well_flux,
        saturation_excess_rate_m_s=saturation_excess_rate,
        internal_edge_flux_m3_s=internal_edge_flux,
        internal_flux_residual_m3_s=internal_flux_residual,
        boundary_edge_flux_m3_s=boundary_edge_flux,
        boundary_head_flux_residual_m3_s=boundary_head_flux_residual,
        drainage_flux_m3_s=drainage_flux,
    )

__all__ = [
    "BoussinesqAssembly",
    "apply_prescribed_head_to_cells",
    "accumulate_boundary_flux_residual",
    "accumulate_internal_flux_residual",
    "assemble_steady_residual",
    "assemble_steady_residual_with_saturation_excess",
    "assemble_transient_residual",
    "assemble_transient_residual_with_saturation_excess",
    "boundary_head_edge_flux_from_head",
    "drainage_outflow_from_head",
    "internal_edge_flux_from_head",
    "resolve_boundary_head_inputs",
    "regularized_partition_surface_rate_from_balance",
    "saturated_thickness_from_head",
    "saturation_excess_rate_from_balance",
    "transmissivity_from_head",
]


resolve_boundary_head_inputs = _resolve_boundary_head_inputs
