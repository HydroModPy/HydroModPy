"""Input-normalization helpers for Boussinesq assembly and Jacobians."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly.types import _BoundaryHeadInputs
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def as_cell_vector(
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


def as_prescribed_head_cell_vector(
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
        raise ValueError(f"{label} must have length {int(n_cells)}; got {int(array.size)}.")
    return array.astype(float, copy=False)


def as_edge_vector(
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
        raise ValueError(f"{label} must have length {int(n_edges)}; got {int(array.size)}.")
    return array.astype(float, copy=False)


def apply_prescribed_head_to_cells(
    head_m: np.ndarray,
    *,
    prescribed_head_m_by_cell: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Overwrite prescribed cells with their Dirichlet value."""
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    prescribed = as_prescribed_head_cell_vector(
        prescribed_head_m_by_cell,
        n_cells=head.size,
        label="prescribed_head_m_by_cell",
    )
    mask = np.isfinite(prescribed)
    if np.any(mask):
        head[mask] = prescribed[mask]
    return head, prescribed


def resolve_boundary_head_inputs(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None,
) -> _BoundaryHeadInputs:
    """Normalize the two supported Dirichlet representations to one internal view."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    if head.size != int(mesh.n_cells):
        raise ValueError(
            f"head_m length must match mesh.n_cells ({head.size} != {int(mesh.n_cells)})."
        )
    boundary_head = as_edge_vector(
        boundary_head_m_by_edge,
        n_edges=mesh.n_edges,
        label="boundary_head_m_by_edge",
    )
    prescribed_head = as_prescribed_head_cell_vector(
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


def finalize_boundary_constrained_residual(
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


__all__ = [
    "apply_prescribed_head_to_cells",
    "as_cell_vector",
    "as_edge_vector",
    "as_prescribed_head_cell_vector",
    "finalize_boundary_constrained_residual",
    "resolve_boundary_head_inputs",
]
