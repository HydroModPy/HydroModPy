"""Finite-difference Jacobians of a head residual, dense, sparse and with coloured columns.

The test residual is linear, F(h) = A h with A the stiffness matrix of a chain of cells, so the
forward difference returns A to rounding error. A chain of n cells has n - 1 interior edges.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.jacobian.fd import (
    build_cell_coupling_rows_by_column,
    build_colored_sparse_fd_jacobian_triplets,
    build_dense_fd_jacobian,
    build_sparse_fd_jacobian_triplets,
    color_columns_by_row_overlap,
)

pytestmark = pytest.mark.fast

REL_STEP = 1.0e-6
N_CELLS = 5


def chain_matrix(n_cells: int = N_CELLS) -> np.ndarray:
    """Tridiagonal matrix of a chain of cells, 2 on the diagonal and -1 between neighbours."""
    return 2.0 * np.eye(n_cells) - np.eye(n_cells, k=1) - np.eye(n_cells, k=-1)


def chain_rows(n_cells: int = N_CELLS) -> tuple[np.ndarray, ...]:
    edges = np.arange(n_cells - 1)
    return build_cell_coupling_rows_by_column(
        n_cells=n_cells, edge_cell_a=edges, edge_cell_b=edges + 1
    )


def linear_residual(head: np.ndarray) -> np.ndarray:
    return chain_matrix(head.size) @ head


def dense_of(triplets: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    data, rows, cols = triplets
    out = np.zeros((N_CELLS, N_CELLS))
    np.add.at(out, (rows, cols), data)
    return out


HEAD = np.array([10.0, 12.0, 15.0, 11.0, 9.0])


def test_dense_jacobian_of_a_linear_residual() -> None:
    jac = build_dense_fd_jacobian(linear_residual, HEAD, linear_residual(HEAD), rel_step=REL_STEP)

    np.testing.assert_allclose(jac, chain_matrix(), atol=1e-4)


def test_coupling_rows_follow_the_interior_edges() -> None:
    rows = chain_rows(3)

    # A boundary edge (neighbour -1) adds no coupling. A cell depends on itself and its neighbours.
    with_boundary = build_cell_coupling_rows_by_column(
        n_cells=3, edge_cell_a=np.array([0, 1, 2]), edge_cell_b=np.array([1, 2, -1])
    )
    for got in (rows, with_boundary):
        assert [r.tolist() for r in got] == [[0, 1], [0, 1, 2], [1, 2]]


@pytest.mark.parametrize("build", ["sparse", "colored"])
def test_sparse_jacobian_of_a_linear_residual(build) -> None:
    rows = chain_rows()
    residual0 = linear_residual(HEAD)
    if build == "sparse":
        triplets = build_sparse_fd_jacobian_triplets(
            linear_residual, HEAD, residual0, rows_by_col=rows, rel_step=REL_STEP
        )
    else:
        triplets = build_colored_sparse_fd_jacobian_triplets(
            linear_residual,
            HEAD,
            residual0,
            rows_by_col=rows,
            column_groups=color_columns_by_row_overlap(rows),
            rel_step=REL_STEP,
        )

    np.testing.assert_allclose(dense_of(triplets), chain_matrix(), atol=1e-4)


def test_columns_sharing_no_row_share_a_colour() -> None:
    groups = color_columns_by_row_overlap(chain_rows())

    # Columns 0 and 3 touch rows {0, 1} and {2, 3, 4}, so they can be perturbed together.
    assert sorted(np.concatenate(groups).tolist()) == [0, 1, 2, 3, 4]
    assert len(groups) == 3
    assert color_columns_by_row_overlap(()) == ()
    free = color_columns_by_row_overlap((np.array([0]), np.array([], dtype=int), np.array([0])))
    # Columns that each touch their own row are all free of each other.
    alone = color_columns_by_row_overlap((np.array([0]), np.array([1])))
    assert [g.tolist() for g in alone] == [[0, 1]]
    # Columns 0 and 2 share row 0. Column 1 has no row and joins the first group.
    assert [g.tolist() for g in free] == [[0, 1], [2]]


def test_columns_without_rows_give_no_entries() -> None:
    head = np.array([1.0, 2.0])
    residual0 = linear_residual(head)
    rows = (np.array([], dtype=int), np.array([], dtype=int))
    sparse = build_sparse_fd_jacobian_triplets(
        linear_residual, head, residual0, rows_by_col=rows, rel_step=REL_STEP
    )
    colored = build_colored_sparse_fd_jacobian_triplets(
        linear_residual,
        head,
        residual0,
        rows_by_col=rows,
        column_groups=(np.array([], dtype=int), np.array([0, 1])),
        rel_step=REL_STEP,
    )

    for data, row, col in (sparse, colored):
        assert data.size == row.size == col.size == 0


def colored(rows, groups):
    return build_colored_sparse_fd_jacobian_triplets(
        linear_residual,
        HEAD,
        linear_residual(HEAD),
        rows_by_col=rows,
        column_groups=groups,
        rel_step=REL_STEP,
    )


REFUSALS = [
    pytest.param(
        lambda: build_cell_coupling_rows_by_column(
            n_cells=-1, edge_cell_a=np.array([]), edge_cell_b=np.array([])
        ),
        "must be non-negative",
        id="negative cell count",
    ),
    pytest.param(
        lambda: build_cell_coupling_rows_by_column(
            n_cells=3, edge_cell_a=np.array([0, 1]), edge_cell_b=np.array([1])
        ),
        "same length",
        id="edge arrays of different lengths",
    ),
    pytest.param(
        lambda: build_cell_coupling_rows_by_column(
            n_cells=3, edge_cell_a=np.array([3]), edge_cell_b=np.array([0])
        ),
        r"edge_cell_a\[0\]=3 is outside \[0, 2\]",
        id="owner out of range",
    ),
    pytest.param(
        lambda: build_cell_coupling_rows_by_column(
            n_cells=3, edge_cell_a=np.array([0]), edge_cell_b=np.array([3])
        ),
        r"edge_cell_b\[0\]=3 is outside \[0, 2\]",
        id="neighbour out of range",
    ),
    pytest.param(
        lambda: build_sparse_fd_jacobian_triplets(
            linear_residual, HEAD, HEAD, rows_by_col=chain_rows(3), rel_step=REL_STEP
        ),
        "rows_by_col length must match",
        id="sparse stencil of the wrong size",
    ),
    pytest.param(
        lambda: colored(chain_rows(3), (np.arange(5),)),
        "rows_by_col length must match",
        id="colored stencil of the wrong size",
    ),
    pytest.param(
        lambda: colored(chain_rows(), (np.array([0, 7]),)),
        r"column 7 outside \[0, 4\]",
        id="column out of range",
    ),
    pytest.param(
        lambda: colored(chain_rows(), (np.array([0, 3]), np.array([1, 4]))),
        "each column exactly once",
        id="column left out of the groups",
    ),
]


@pytest.mark.parametrize(("call", "message"), REFUSALS)
def test_refusals(call, message) -> None:
    with pytest.raises(ValueError, match=message):
        call()
