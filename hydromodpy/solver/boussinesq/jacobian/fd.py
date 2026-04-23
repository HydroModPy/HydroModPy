"""Finite-difference Jacobian helpers for Boussinesq runtimes.

At the moment the Boussinesq backends share a deliberately simple strategy:

- keep the nonlinear unknown equal to the cell-centered head vector;
- evaluate the residual as a black-box function of that vector;
- approximate the Jacobian by forward finite differences.

This module now exposes both:

- a dense builder used by the historical ``local`` and ``scipy`` runtimes;
- sparse-oriented helpers that derive a cell-coupling stencil from mesh
  connectivity and keep only those entries in the assembled Jacobian.

The sparse path also supports a simple greedy column coloring so structurally
independent columns can be perturbed together. That keeps the physics black-box
while reducing the number of residual evaluations needed for one sparse FD
Jacobian build.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np


def build_dense_fd_jacobian(
    residual_fn: Callable[[np.ndarray], np.ndarray],
    head_m: np.ndarray,
    residual0: np.ndarray,
    *,
    rel_step: float,
) -> np.ndarray:
    """Build a dense Jacobian by perturbing one head component at a time.

    Parameters
    ----------
    residual_fn:
        Callable returning the assembled residual for a candidate head vector.
    head_m:
        Current nonlinear iterate.
    residual0:
        Residual already evaluated at ``head_m``. Passing it in avoids one extra
        residual evaluation per Newton iteration.
    rel_step:
        Relative perturbation used for the forward finite difference.
    """
    head = np.asarray(head_m, dtype=float)
    residual_base = np.asarray(residual0, dtype=float)
    n_cells = int(head.size)
    jacobian = np.zeros((n_cells, n_cells), dtype=float)
    for col in range(n_cells):
        # Scale the perturbation with the current head magnitude so columns
        # remain meaningful for both shallow and deep water tables.
        step = rel_step * max(1.0, abs(float(head[col])))
        perturbed = head.copy()
        perturbed[col] += step
        residual_perturbed = np.asarray(residual_fn(perturbed), dtype=float)
        jacobian[:, col] = (residual_perturbed - residual_base) / step
    return jacobian


def build_cell_coupling_rows_by_column(
    *,
    n_cells: int,
    edge_cell_a: np.ndarray,
    edge_cell_b: np.ndarray,
) -> tuple[np.ndarray, ...]:
    """Return the residual rows that can depend on each head unknown.

    For the current finite-volume discretization, one cell residual depends on:

    - its own head,
    - the head of directly adjacent cells connected by one interior edge.

    Boundary-stage, drainage and storage contributions remain cell-local, so
    the adjacency graph of interior edges is enough to describe the Jacobian
    sparsity pattern for both steady and transient residuals.
    """
    n_cells_int = int(n_cells)
    if n_cells_int < 0:
        raise ValueError("n_cells must be non-negative.")

    cell_a = np.asarray(edge_cell_a, dtype=int).reshape(-1)
    cell_b = np.asarray(edge_cell_b, dtype=int).reshape(-1)
    if cell_a.size != cell_b.size:
        raise ValueError("edge_cell_a and edge_cell_b must have the same length.")

    coupling: list[set[int]] = [{int(index)} for index in range(n_cells_int)]
    for edge_index in range(cell_a.size):
        owner = int(cell_a[edge_index])
        neighbour = int(cell_b[edge_index])
        if owner < 0 or owner >= n_cells_int:
            raise ValueError(
                f"edge_cell_a[{edge_index}]={owner} is outside [0, {n_cells_int - 1}]."
            )
        if neighbour < 0:
            continue
        if neighbour >= n_cells_int:
            raise ValueError(
                f"edge_cell_b[{edge_index}]={neighbour} is outside [0, {n_cells_int - 1}]."
            )
        coupling[owner].add(neighbour)
        coupling[neighbour].add(owner)

    return tuple(np.asarray(sorted(rows), dtype=int) for rows in coupling)


def build_sparse_fd_jacobian_triplets(
    residual_fn: Callable[[np.ndarray], np.ndarray],
    head_m: np.ndarray,
    residual0: np.ndarray,
    *,
    rows_by_col: tuple[np.ndarray, ...],
    rel_step: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build sparse Jacobian triplets using a precomputed coupling stencil.

    The result is returned as ``(data, row_indices, col_indices)`` so runtime
    backends can choose their preferred sparse matrix container without forcing
    an unconditional SciPy import here.
    """
    head = np.asarray(head_m, dtype=float)
    residual_base = np.asarray(residual0, dtype=float)
    n_cells = int(head.size)
    if len(rows_by_col) != n_cells:
        raise ValueError(
            "rows_by_col length must match the head vector length "
            f"({len(rows_by_col)} != {n_cells})."
        )

    data_parts: list[np.ndarray] = []
    row_parts: list[np.ndarray] = []
    col_parts: list[np.ndarray] = []

    for col in range(n_cells):
        active_rows = np.asarray(rows_by_col[col], dtype=int).reshape(-1)
        if active_rows.size == 0:
            continue
        step = rel_step * max(1.0, abs(float(head[col])))
        perturbed = head.copy()
        perturbed[col] += step
        residual_perturbed = np.asarray(residual_fn(perturbed), dtype=float)
        column_values = (residual_perturbed[active_rows] - residual_base[active_rows]) / step
        data_parts.append(column_values.astype(float, copy=False))
        row_parts.append(active_rows.astype(int, copy=False))
        col_parts.append(np.full(active_rows.size, col, dtype=int))

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


def color_columns_by_row_overlap(
    rows_by_col: tuple[np.ndarray, ...],
) -> tuple[np.ndarray, ...]:
    """Group columns whose structural row supports do not overlap.

    Two columns can share the same finite-difference residual evaluation only if
    they never contribute to the same residual row. The input ``rows_by_col``
    already encodes that structural support, so the coloring problem reduces to
    a graph where:

    - columns are vertices,
    - an edge exists when two columns share at least one active residual row.

    A simple largest-degree-first greedy coloring is enough here. It keeps the
    algorithm deterministic and lightweight while usually reducing the number
    of residual evaluations substantially on strip- and mesh-like stencils.
    """
    n_cols = len(rows_by_col)
    if n_cols == 0:
        return ()

    row_to_cols: dict[int, list[int]] = {}
    for col, raw_rows in enumerate(rows_by_col):
        rows = np.asarray(raw_rows, dtype=int).reshape(-1)
        if rows.size == 0:
            continue
        for row in rows.tolist():
            row_to_cols.setdefault(int(row), []).append(int(col))

    neighbours: list[set[int]] = [set() for _ in range(n_cols)]
    for cols in row_to_cols.values():
        if len(cols) <= 1:
            continue
        for col in cols:
            neighbours[col].update(other for other in cols if other != col)

    order = sorted(
        range(n_cols),
        key=lambda col: (-len(neighbours[col]), col),
    )
    color_by_col = [-1] * n_cols
    for col in order:
        forbidden = {color_by_col[other] for other in neighbours[col] if color_by_col[other] >= 0}
        color = 0
        while color in forbidden:
            color += 1
        color_by_col[col] = color

    n_colors = max(color_by_col) + 1
    groups: list[list[int]] = [[] for _ in range(n_colors)]
    for col, color in enumerate(color_by_col):
        groups[int(color)].append(int(col))

    return tuple(np.asarray(group, dtype=int) for group in groups)


def build_colored_sparse_fd_jacobian_triplets(
    residual_fn: Callable[[np.ndarray], np.ndarray],
    head_m: np.ndarray,
    residual0: np.ndarray,
    *,
    rows_by_col: tuple[np.ndarray, ...],
    column_groups: tuple[np.ndarray, ...],
    rel_step: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build sparse Jacobian triplets using graph-colored FD perturbations.

    ``column_groups`` must partition the columns into sets with disjoint row
    supports. Each group then requires only one residual evaluation, no matter
    how many columns it contains.
    """
    head = np.asarray(head_m, dtype=float)
    residual_base = np.asarray(residual0, dtype=float)
    n_cells = int(head.size)
    if len(rows_by_col) != n_cells:
        raise ValueError(
            "rows_by_col length must match the head vector length "
            f"({len(rows_by_col)} != {n_cells})."
        )

    assigned_cols: list[int] = []
    data_parts: list[np.ndarray] = []
    row_parts: list[np.ndarray] = []
    col_parts: list[np.ndarray] = []

    for raw_group in column_groups:
        group = np.asarray(raw_group, dtype=int).reshape(-1)
        if group.size == 0:
            continue
        assigned_cols.extend(group.tolist())
        perturbed = head.copy()
        step_by_col: dict[int, float] = {}
        for col in group.tolist():
            if col < 0 or col >= n_cells:
                raise ValueError(f"column_groups contains column {col} outside [0, {n_cells - 1}].")
            step = rel_step * max(1.0, abs(float(head[col])))
            perturbed[col] += step
            step_by_col[int(col)] = float(step)

        residual_perturbed = np.asarray(residual_fn(perturbed), dtype=float)
        for col in group.tolist():
            active_rows = np.asarray(rows_by_col[col], dtype=int).reshape(-1)
            if active_rows.size == 0:
                continue
            column_values = (residual_perturbed[active_rows] - residual_base[active_rows]) / float(
                step_by_col[int(col)]
            )
            data_parts.append(column_values.astype(float, copy=False))
            row_parts.append(active_rows.astype(int, copy=False))
            col_parts.append(np.full(active_rows.size, int(col), dtype=int))

    expected_cols = list(range(n_cells))
    if sorted(assigned_cols) != expected_cols:
        raise ValueError(
            "column_groups must contain each column exactly once. "
            f"Got {sorted(assigned_cols)} for expected {expected_cols}."
        )

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
    "build_cell_coupling_rows_by_column",
    "build_colored_sparse_fd_jacobian_triplets",
    "build_dense_fd_jacobian",
    "color_columns_by_row_overlap",
    "build_sparse_fd_jacobian_triplets",
]
