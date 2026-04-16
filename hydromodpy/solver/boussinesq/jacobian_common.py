"""Common helpers shared by semianalytic Boussinesq Jacobian builders."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def saturated_thickness_derivative_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> np.ndarray:
    """Return the piecewise derivative of saturated thickness with respect to head."""
    head = np.asarray(head_m, dtype=float)
    max_thickness = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    raw_thickness = head - mesh.z_bottom_m
    active = (raw_thickness > 0.0) & (raw_thickness < max_thickness)
    return active.astype(float, copy=False)


def drainage_diagonal_derivative(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> np.ndarray:
    """Return the diagonal derivative of the top-drainage operator."""
    if drainage_conductance_m2_s is None:
        return np.zeros(mesh.n_cells, dtype=float)
    conductance = as_cell_vector(
        drainage_conductance_m2_s,
        n_cells=mesh.n_cells,
    )
    auto_conductance = mesh.hydraulic_conductivity_m_s * mesh.cell_area_m2
    effective_conductance = np.where(conductance > 0.0, conductance, auto_conductance)
    head = np.asarray(head_m, dtype=float)
    active = head > mesh.z_top_m
    return np.where(active, effective_conductance, 0.0).astype(float, copy=False)


def saturated_thickness_value(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    cell_index: int,
) -> float:
    """Return the saturated thickness in one cell as a scalar float."""
    max_thickness = max(
        float(mesh.z_top_m[cell_index] - mesh.z_bottom_m[cell_index]),
        0.0,
    )
    raw = float(np.asarray(head_m, dtype=float)[cell_index] - mesh.z_bottom_m[cell_index])
    return float(np.clip(raw, 0.0, max_thickness))


def harmonic_conductivity(
    conductivity_a_m_s: float,
    conductivity_b_m_s: float,
) -> float:
    """Return the harmonic mean conductivity used in Jacobian edge operators."""
    if conductivity_a_m_s <= 0.0 or conductivity_b_m_s <= 0.0:
        return 0.0
    return 2.0 / ((1.0 / conductivity_a_m_s) + (1.0 / conductivity_b_m_s))


def as_cell_vector(
    values: np.ndarray | float | None,
    *,
    n_cells: int,
) -> np.ndarray:
    """Return a scalar or vector payload as one cell-aligned float array."""
    if values is None:
        return np.zeros(n_cells, dtype=float)
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0:
        return np.zeros(n_cells, dtype=float)
    if array.size == 1:
        return np.full(n_cells, float(array[0]), dtype=float)
    if array.size != int(n_cells):
        raise ValueError(
            f"Expected scalar or vector of length {int(n_cells)}; got {int(array.size)}."
        )
    return array.astype(float, copy=False)


def concatenate_triplets(
    *triplet_sets: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Concatenate sparse COO triplet sets while ignoring empty pieces."""
    data_parts: list[np.ndarray] = []
    row_parts: list[np.ndarray] = []
    col_parts: list[np.ndarray] = []
    for data, row_indices, col_indices in triplet_sets:
        if np.asarray(data).size == 0:
            continue
        data_parts.append(np.asarray(data, dtype=float).reshape(-1))
        row_parts.append(np.asarray(row_indices, dtype=int).reshape(-1))
        col_parts.append(np.asarray(col_indices, dtype=int).reshape(-1))
    if not data_parts:
        return (
            np.asarray([], dtype=float),
            np.asarray([], dtype=int),
            np.asarray([], dtype=int),
        )
    return (
        np.concatenate(data_parts).astype(float, copy=False),
        np.concatenate(row_parts).astype(int, copy=False),
        np.concatenate(col_parts).astype(int, copy=False),
    )


__all__ = [
    "as_cell_vector",
    "concatenate_triplets",
    "drainage_diagonal_derivative",
    "harmonic_conductivity",
    "saturated_thickness_derivative_from_head",
    "saturated_thickness_value",
]
