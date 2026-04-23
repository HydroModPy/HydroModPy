"""Mesh fixtures for the test suite.

Provides reusable :class:`~hydromodpy.spatial.mesh.HydroMesh` builders for
quick structured grids used across unit, integration and e2e tests. Each
factory is pure (no I/O) and deterministic so fixtures can be cached with
session scope when used through pytest.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh


def cartesian_quad_mesh(
    nx: int,
    ny: int,
    *,
    dx: float = 1.0,
    dy: float = 1.0,
    x0: float = 0.0,
    y0: float = 0.0,
) -> HydroMesh:
    """Build a 2D structured quadrilateral mesh with ``nx * ny`` cells."""
    xs = x0 + np.arange(nx + 1, dtype=float) * float(dx)
    ys = y0 + np.arange(ny + 1, dtype=float) * float(dy)
    xv, yv = np.meshgrid(xs, ys, indexing="xy")
    vertices = np.column_stack([xv.ravel(), yv.ravel()])

    n_col_nodes = nx + 1
    conn = np.empty((nx * ny, 4), dtype=int)
    idx = 0
    for j in range(ny):
        for i in range(nx):
            p0 = j * n_col_nodes + i
            p1 = p0 + 1
            p2 = p1 + n_col_nodes
            p3 = p0 + n_col_nodes
            conn[idx] = (p0, p1, p2, p3)
            idx += 1
    block = CellBlock(cell_type=CellType.QUADRILATERAL, connectivity=conn)
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(block,),
        structured_shape=(ny, nx),
    )


@pytest.fixture(scope="session")
def mini_cartesian_3x3() -> HydroMesh:
    """3x3 quad grid (dx=dy=1m) - cheap unit fixture."""
    return cartesian_quad_mesh(nx=3, ny=3, dx=1.0, dy=1.0)


@pytest.fixture(scope="session")
def mini_cartesian_10x10() -> HydroMesh:
    """10x10 quad grid (dx=dy=10m) - small integration fixture."""
    return cartesian_quad_mesh(nx=10, ny=10, dx=10.0, dy=10.0)


@pytest.fixture(scope="module")
def cartesian_101x101() -> HydroMesh:
    """101x101 quad grid (dx=dy=1m) - MMS / convergence fixture."""
    return cartesian_quad_mesh(nx=101, ny=101, dx=1.0, dy=1.0)


@pytest.fixture(params=[(1, 1), (1, 5), (5, 1), (2, 3), (3, 3)])
def degenerate_mesh(request) -> HydroMesh:
    """Parameterized 1D / tiny grids for edge-case coverage."""
    nx, ny = request.param
    return cartesian_quad_mesh(nx=nx, ny=ny, dx=1.0, dy=1.0)
