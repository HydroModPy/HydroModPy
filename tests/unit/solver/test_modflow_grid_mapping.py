from __future__ import annotations

import numpy as np

from hydromodpy.solver.modflow_grid.grid_mapping import describe_grid
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


def test_describe_grid_preserves_nonuniform_structured_spacing() -> None:
    vertices = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [3.0, 0.0],
            [0.0, 2.0],
            [1.0, 2.0],
            [3.0, 2.0],
            [0.0, 5.0],
            [1.0, 5.0],
            [3.0, 5.0],
        ],
        dtype=float,
    )
    connectivity = np.array(
        [
            [0, 1, 4, 3],
            [1, 2, 5, 4],
            [3, 4, 7, 6],
            [4, 5, 8, 7],
        ],
        dtype=int,
    )
    planar = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
        structured_shape=(2, 2),
    )
    mesh = SolverMesh(
        planar_mesh=planar,
        top=np.full(4, 10.0),
        botm=np.full((1, 4), 0.0),
        inactive_mask=np.zeros((1, 4), dtype=bool),
    )

    descriptor = describe_grid(mesh)

    np.testing.assert_allclose(descriptor.delr, [1.0, 2.0])
    np.testing.assert_allclose(descriptor.delc, [2.0, 3.0])
