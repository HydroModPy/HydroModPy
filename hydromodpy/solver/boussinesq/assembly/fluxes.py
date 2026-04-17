"""Flux and transmissivity operators used by the Boussinesq assembly."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly.inputs import (
    as_cell_vector,
    as_edge_vector,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

_MIN_DISTANCE_M = 1.0e-12


def saturated_thickness_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> np.ndarray:
    """Return the saturated thickness ``b(h)`` in each cell."""
    max_thickness = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    return np.clip(np.asarray(head_m, dtype=float) - mesh.z_bottom_m, 0.0, max_thickness)


def transmissivity_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> np.ndarray:
    """Return the cell transmissivity ``T(h) = K b(h)``."""
    saturated_thickness_m = saturated_thickness_from_head(mesh, head_m)
    return mesh.hydraulic_conductivity_m_s * saturated_thickness_m


def harmonic_conductivity(
    conductivity_a_m_s: float,
    conductivity_b_m_s: float,
) -> float:
    """Return the harmonic mean conductivity used on one interior edge."""
    if conductivity_a_m_s <= 0.0 or conductivity_b_m_s <= 0.0:
        return 0.0
    return 2.0 / ((1.0 / conductivity_a_m_s) + (1.0 / conductivity_b_m_s))


def edge_to_stage_tau_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return transmissive factors used for edge-supported boundary exchanges."""
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
    boundary_heads = as_edge_vector(
        boundary_head_m_by_edge,
        n_edges=mesh.n_edges,
        label="boundary_head_m_by_edge",
    )
    tau_a, tau_b = edge_to_stage_tau_from_head(mesh, head_m)
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


def internal_edge_flux_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> np.ndarray:
    """Return one oriented inter-cell flux per edge."""
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
        conductivity_edge = harmonic_conductivity(conductivity_a, conductivity_b)
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
    """Return one drainage outflow per cell."""
    if drainage_conductance_m2_s is None:
        return np.zeros(mesh.n_cells, dtype=float)
    conductance = as_cell_vector(
        drainage_conductance_m2_s,
        n_cells=mesh.n_cells,
        label="drainage_conductance_m2_s",
    )
    auto_conductance = mesh.hydraulic_conductivity_m_s * mesh.cell_area_m2
    effective_conductance = np.where(conductance > 0.0, conductance, auto_conductance)
    head = np.asarray(head_m, dtype=float)
    return effective_conductance * np.maximum(head - mesh.z_top_m, 0.0)


__all__ = [
    "accumulate_boundary_flux_residual",
    "accumulate_internal_flux_residual",
    "boundary_head_edge_flux_from_head",
    "drainage_outflow_from_head",
    "edge_to_stage_tau_from_head",
    "harmonic_conductivity",
    "internal_edge_flux_from_head",
    "saturated_thickness_from_head",
    "transmissivity_from_head",
]

