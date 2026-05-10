"""Variable-bound helpers shared by PETSc Boussinesq VI runtimes."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

UNBOUNDED_HEAD_UPPER_M = 1.0e30


def variable_bounds(
    mesh: BoussinesqMesh,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return PETSc VI lower/upper vectors and the prescribed-cell mask.

    Without explicit top drainage, the free-head obstacle is
    ``z_bottom <= h <= z_top``. With a positive Cauchy drainage conductance,
    the upper obstacle is relaxed so the drainage flux term carries top
    exchange consistently with the MODFLOW 6 drain package.
    """
    lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1).copy()
    upper = upper_bounds_for_drainage_policy(
        mesh=mesh,
        lower_m=lower,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    prescribed = (
        np.full(int(mesh.n_cells), np.nan, dtype=float)
        if prescribed_head_m_by_cell is None
        else np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)
    )
    if prescribed.size != int(mesh.n_cells):
        raise ValueError(
            "prescribed_head_m_by_cell must have length "
            f"{int(mesh.n_cells)}; got {int(prescribed.size)}."
        )
    prescribed_mask = np.isfinite(prescribed)
    if np.any(prescribed_mask):
        lower[prescribed_mask] = prescribed[prescribed_mask]
        upper[prescribed_mask] = prescribed[prescribed_mask]
    return lower, upper, prescribed_mask


def upper_bounds_for_drainage_policy(
    *,
    mesh: BoussinesqMesh,
    lower_m: np.ndarray,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> np.ndarray:
    """Return VI upper bounds consistent with the configured top exchange."""
    top = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), lower_m)
    if not has_positive_drainage_conductance(
        drainage_conductance_m2_s,
        n_cells=int(mesh.n_cells),
    ):
        return top
    return np.full(int(mesh.n_cells), UNBOUNDED_HEAD_UPPER_M, dtype=float)


def has_positive_drainage_conductance(
    drainage_conductance_m2_s: np.ndarray | float | None,
    *,
    n_cells: int,
) -> bool:
    """Return whether a finite-conductance top drainage BC is explicitly active."""
    if drainage_conductance_m2_s is None:
        return False
    values = np.asarray(drainage_conductance_m2_s, dtype=float).reshape(-1)
    if values.size == 1:
        values = np.full(int(n_cells), float(values[0]), dtype=float)
    elif values.size != int(n_cells):
        raise ValueError(
            "drainage_conductance_m2_s must be scalar or have length "
            f"{int(n_cells)}; got {int(values.size)}."
        )
    finite = values[np.isfinite(values)]
    return bool(finite.size and np.any(finite > 0.0))


__all__ = [
    "UNBOUNDED_HEAD_UPPER_M",
    "has_positive_drainage_conductance",
    "upper_bounds_for_drainage_policy",
    "variable_bounds",
]
