"""Shared PETSc helpers for Boussinesq runtimes."""

from __future__ import annotations

import platform

import numpy as np


def _require_petsc():
    """Import PETSc lazily and fail with one explicit Linux-only message."""
    system_name = platform.system()
    if str(system_name).strip().lower() != "linux":
        raise RuntimeError(
            "Boussinesq runtime_backend='petsc' is only supported on Linux. "
            f"Current platform: {system_name or '<unknown>'}."
        )
    try:
        from petsc4py import PETSc
    except Exception as exc:  # pragma: no cover - depends on optional import state
        raise RuntimeError(
            "Boussinesq runtime_backend='petsc' requires petsc4py to be installed "
            "in the active Linux environment."
        ) from exc
    return PETSc


def _coo_to_csr(
    *,
    n_rows: int,
    n_cols: int,
    row_indices: np.ndarray,
    col_indices: np.ndarray,
    data: np.ndarray,
    index_dtype,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert one sparse COO triplet set into CSR while summing duplicates."""
    rows = np.asarray(row_indices, dtype=index_dtype).reshape(-1)
    cols = np.asarray(col_indices, dtype=index_dtype).reshape(-1)
    values = np.asarray(data, dtype=float).reshape(-1)
    if rows.size == 0:
        return (
            np.zeros(int(n_rows) + 1, dtype=index_dtype),
            np.zeros(0, dtype=index_dtype),
            np.zeros(0, dtype=float),
        )
    order = np.lexsort((cols, rows))
    rows = rows[order]
    cols = cols[order]
    values = values[order]

    indptr = np.zeros(int(n_rows) + 1, dtype=index_dtype)
    out_cols: list[int] = []
    out_data: list[float] = []
    cursor = 0
    for row in range(int(n_rows)):
        while cursor < rows.size and rows[cursor] < row:
            cursor += 1
        row_start = cursor
        while cursor < rows.size and rows[cursor] == row:
            cursor += 1
        row_end = cursor
        if row_end > row_start:
            current_col = int(cols[row_start])
            current_value = float(values[row_start])
            for item_index in range(row_start + 1, row_end):
                item_col = int(cols[item_index])
                item_value = float(values[item_index])
                if item_col == current_col:
                    current_value += item_value
                else:
                    out_cols.append(current_col)
                    out_data.append(current_value)
                    current_col = item_col
                    current_value = item_value
            out_cols.append(current_col)
            out_data.append(current_value)
        indptr[row + 1] = len(out_cols)

    col_array = np.asarray(out_cols, dtype=index_dtype)
    data_array = np.asarray(out_data, dtype=float)
    if col_array.size != 0 and (
        np.any(col_array < 0) or np.any(col_array >= int(n_cols))
    ):
        raise ValueError("CSR column indices are out of range.")
    return indptr, col_array, data_array


def _configure_default_snes(
    snes,
    *,
    tol_residual_inf: float,
    max_iterations: int,
    prefer_direct_linear_solve: bool = False,
) -> None:
    """Apply the default PETSc nonlinear and linear solver settings."""
    snes.setType("newtonls")
    snes.setTolerances(
        atol=float(tol_residual_inf),
        rtol=0.0,
        stol=0.0,
        max_it=int(max_iterations),
    )
    line_search = snes.getLineSearch()
    if line_search is not None:
        line_search.setType("bt")
        line_search.setFromOptions()
    ksp = snes.getKSP()
    if ksp is not None:
        if prefer_direct_linear_solve:
            ksp.setType("preonly")
            ksp.setTolerances(rtol=1.0e-12, atol=0.0, max_it=1)
        else:
            ksp.setType("gmres")
            ksp.setTolerances(rtol=1.0e-10, atol=0.0, max_it=1000)
        pc = ksp.getPC()
        if pc is not None:
            pc.setType("lu" if prefer_direct_linear_solve else "ilu")
            pc.setFromOptions()
        ksp.setFromOptions()
    snes.setFromOptions()


def _snes_reason_label(reason: int) -> str:
    """Return one readable label for a PETSc SNES converged/diverged reason."""
    labels = {
        2: "SNES_CONVERGED_FNORM_ABS",
        3: "SNES_CONVERGED_FNORM_RELATIVE",
        4: "SNES_CONVERGED_SNORM_RELATIVE",
        5: "SNES_CONVERGED_ITS",
        6: "SNES_BREAKOUT_INNER_ITER",
        7: "SNES_CONVERGED_USER",
        -1: "SNES_DIVERGED_FUNCTION_DOMAIN",
        -2: "SNES_DIVERGED_FUNCTION_COUNT",
        -3: "SNES_DIVERGED_LINEAR_SOLVE",
        -4: "SNES_DIVERGED_FUNCTION_NANORINF",
        -5: "SNES_DIVERGED_MAX_IT",
        -6: "SNES_DIVERGED_LINE_SEARCH",
        -7: "SNES_DIVERGED_INNER",
        -8: "SNES_DIVERGED_LOCAL_MIN",
        -9: "SNES_DIVERGED_DTOL",
        -10: "SNES_DIVERGED_JACOBIAN_DOMAIN",
        -11: "SNES_DIVERGED_TR_DELTA",
        -12: "SNES_DIVERGED_USER",
        -13: "SNES_DIVERGED_OBJECTIVE_DOMAIN",
        -14: "SNES_DIVERGED_OBJECTIVE_NANORINF",
        0: "SNES_CONVERGED_ITERATING",
    }
    return labels.get(int(reason), f"SNES_REASON_{int(reason)}")


__all__ = [
    "_configure_default_snes",
    "_coo_to_csr",
    "_require_petsc",
    "_snes_reason_label",
]
